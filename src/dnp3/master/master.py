"""DNP3 Master Station implementation per IEEE 1815-2012.

The Master class handles communication with an outstation,
including polling, commands, and unsolicited response handling.
"""

import struct
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar

from dnp3.application.builder import (
    build_delay_measure_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.parser import parse_response
from dnp3.core.enums import FunctionCode
from dnp3.master.commands import (
    CommandBuilder,
    DirectOperateTask,
    OperateTask,
    SelectTask,
)
from dnp3.master.config import MasterConfig
from dnp3.master.handler import (
    AnalogValue,
    BinaryValue,
    CounterValue,
    DefaultSOEHandler,
    ResponseInfo,
    SOEHandler,
)
from dnp3.master.polling import (
    ClassPollTask,
    IntegrityPollTask,
    PollScheduler,
    PollTask,
    RangePollTask,
)
from dnp3.master.state import MasterState, MasterStateManager
from dnp3.objects.layout import PointKind, ValueCodec, WireLayout, layout_for

# DNP3 group numbers for parsing
GROUP_BINARY_INPUT = 1
GROUP_BINARY_INPUT_EVENT = 2
GROUP_BINARY_OUTPUT = 10
GROUP_BINARY_OUTPUT_EVENT = 11
GROUP_ANALOG_INPUT = 30
GROUP_ANALOG_INPUT_EVENT = 32
GROUP_ANALOG_OUTPUT = 40
GROUP_ANALOG_OUTPUT_EVENT = 42
GROUP_COUNTER = 20
GROUP_COUNTER_EVENT = 22
GROUP_FROZEN_COUNTER = 21
GROUP_TIME_DELAY = 52

# Quality flag mask
QUALITY_ONLINE = 0x01
QUALITY_STATE = 0x80


# Qualifier field masks (IEEE 1815-2012 Table 4-1).
QUALIFIER_RANGE_MASK = 0x0F
QUALIFIER_PREFIX_MASK = 0x70

# Range specifier codes carrying an object count rather than start/stop indices.
# Event responses use these, with a per-object index prefix.
RANGE_UINT8_COUNT = 0x07
RANGE_UINT16_COUNT = 0x08
RANGE_UINT32_COUNT = 0x09

# Range specifier codes carrying start and stop indices.
RANGE_UINT8_START_STOP = 0x00
RANGE_UINT16_START_STOP = 0x01
RANGE_UINT32_START_STOP = 0x02

# Width in bytes of the count field, by range code.
_COUNT_FIELD_WIDTH = {
    RANGE_UINT8_COUNT: 1,
    RANGE_UINT16_COUNT: 2,
    RANGE_UINT32_COUNT: 4,
}

# Width in bytes of each start/stop field, by range code.
_START_STOP_FIELD_WIDTH = {
    RANGE_UINT8_START_STOP: 1,
    RANGE_UINT16_START_STOP: 2,
    RANGE_UINT32_START_STOP: 4,
}

# Width in bytes of each object's index prefix, by prefix code (Table 4-3).
# Size prefixes (0x40-0x60) are for variable-format objects, which none of the
# measurement groups parsed here use.
_INDEX_PREFIX_WIDTH = {
    0x00: 0,
    0x10: 1,
    0x20: 2,
    0x30: 4,
}


@dataclass(frozen=True, slots=True)
class ObjectLayout:
    """How a block's objects are laid out after the object header.

    Attributes:
        first_index: Index of the first object (start index, or 0 for counts).
        count: Number of objects declared, or None if the range does not say.
        data_offset: Byte offset in the block data where objects begin.
        index_prefix_width: Bytes of index prefix carried by each object.
    """

    first_index: int
    count: int | None
    data_offset: int
    index_prefix_width: int


def _decode_object_layout(qualifier: int, data: bytes) -> ObjectLayout | None:
    """Decode a block's range specifier and index-prefix width from its qualifier.

    Handles both range qualifiers (start/stop, used by static responses) and
    count qualifiers (used by every event response, with a per-object index
    prefix). Returns None when the qualifier's range specifier is one this
    parser does not support, so the caller yields no values rather than
    misreading the payload as data.
    """
    range_code = qualifier & QUALIFIER_RANGE_MASK
    prefix_code = qualifier & QUALIFIER_PREFIX_MASK
    index_prefix_width = _INDEX_PREFIX_WIDTH.get(prefix_code)
    if index_prefix_width is None:
        return None

    count_width = _COUNT_FIELD_WIDTH.get(range_code)
    if count_width is not None:
        if len(data) < count_width:
            return None
        count = int.from_bytes(data[:count_width], "little")
        return ObjectLayout(
            first_index=0,
            count=count,
            data_offset=count_width,
            index_prefix_width=index_prefix_width,
        )

    field_width = _START_STOP_FIELD_WIDTH.get(range_code)
    if field_width is not None:
        if len(data) < field_width * 2:
            return None
        start = int.from_bytes(data[:field_width], "little")
        stop = int.from_bytes(data[field_width : field_width * 2], "little")
        return ObjectLayout(
            first_index=start,
            count=stop - start + 1,
            data_offset=field_width * 2,
            index_prefix_width=index_prefix_width,
        )

    return None


def _iter_object_slots(
    layout: ObjectLayout,
    data: bytes,
    object_width: int,
) -> "Iterator[tuple[int, int]]":
    """Yield (index, payload_offset) for each object in a block.

    The index comes from the object's own prefix when the qualifier carries one,
    and from consecutive numbering off `first_index` otherwise. Iteration stops
    at the declared count or when the remaining bytes cannot hold another whole
    object, so a truncated or over-long block yields only the objects actually
    present.
    """
    offset = layout.data_offset
    ordinal = 0

    while layout.count is None or ordinal < layout.count:
        entry_width = layout.index_prefix_width + object_width
        if offset + entry_width > len(data):
            return

        if layout.index_prefix_width:
            index = int.from_bytes(data[offset : offset + layout.index_prefix_width], "little")
        else:
            index = layout.first_index + ordinal

        yield index, offset + layout.index_prefix_width
        offset += entry_width
        ordinal += 1


def _decode_signed_int(raw: bytes) -> float:
    """Decode a little-endian signed integer as a float."""
    return float(int.from_bytes(raw, "little", signed=True))


def _decode_float32(raw: bytes) -> float:
    """Decode a little-endian IEEE 754 single-precision value."""
    return float(struct.unpack("<f", raw)[0])


def _decode_float64(raw: bytes) -> float:
    """Decode a little-endian IEEE 754 double-precision value."""
    return float(struct.unpack("<d", raw)[0])


# Analog value codecs the master decodes; a layout with any other codec yields no values.
_ANALOG_DECODERS: Mapping[ValueCodec, Callable[[bytes], float]] = MappingProxyType(
    {
        ValueCodec.INT: _decode_signed_int,
        ValueCodec.FLOAT32: _decode_float32,
        ValueCodec.FLOAT64: _decode_float64,
    }
)


def _read_quality(data: bytes, payload: int, *, has_flags: bool) -> tuple[int, int]:
    """Read the optional quality byte, returning (quality, value_offset)."""
    if has_flags:
        return data[payload], payload + 1
    return QUALITY_ONLINE, payload


def _parse_packed_binary(layout: ObjectLayout, data: bytes) -> list[BinaryValue]:
    """Parse bit-packed binary points (g1v1 / g10v1), 8 points per byte.

    Bounded by the range's declared count so the unused high bits of the final
    byte are not reported as real points.
    """
    values: list[BinaryValue] = []
    payload = data[layout.data_offset :]
    total = layout.count if layout.count is not None else len(payload) * 8

    for ordinal in range(total):
        byte_index, bit = divmod(ordinal, 8)
        if byte_index >= len(payload):
            break
        values.append(
            BinaryValue(
                index=layout.first_index + ordinal,
                value=bool((payload[byte_index] >> bit) & 1),
                quality=QUALITY_ONLINE,
            )
        )
    return values


def _block_slots(block: ObjectBlock) -> ObjectLayout | None:
    """Decode a block's range and prefix, or None if it carries nothing decodable."""
    if not block.data:
        return None
    return _decode_object_layout(block.header.qualifier, block.data)


def _decode_binary(block: ObjectBlock, wire: WireLayout) -> list[BinaryValue]:
    """Decode binary input or output points: packed bits, or one flag octet per point."""
    slots = _block_slots(block)
    if slots is None:
        return []
    data = block.data
    if wire.is_packed:
        return _parse_packed_binary(slots, data)

    values: list[BinaryValue] = []
    for index, payload in _iter_object_slots(slots, data, wire.width):
        flags = data[payload]
        values.append(
            BinaryValue(
                index=index,
                value=bool(flags & QUALITY_STATE),
                quality=flags & ~QUALITY_STATE,
            )
        )
    return values


def _decode_analog(block: ObjectBlock, wire: WireLayout) -> list[AnalogValue]:
    """Decode analog input or output points; any trailing time field is skipped."""
    decode = _ANALOG_DECODERS.get(wire.codec)
    slots = _block_slots(block)
    if decode is None or slots is None:
        return []
    data = block.data

    values: list[AnalogValue] = []
    for index, payload in _iter_object_slots(slots, data, wire.width):
        quality, value_offset = _read_quality(data, payload, has_flags=wire.has_flags)
        values.append(
            AnalogValue(
                index=index,
                value=decode(data[value_offset : value_offset + wire.value_width]),
                quality=quality,
            )
        )
    return values


def _decode_counter(block: ObjectBlock, wire: WireLayout) -> list[CounterValue]:
    """Decode counter or frozen counter points; any trailing time field is skipped."""
    slots = _block_slots(block)
    if wire.codec is not ValueCodec.UINT or slots is None:
        return []
    data = block.data

    values: list[CounterValue] = []
    for index, payload in _iter_object_slots(slots, data, wire.width):
        quality, value_offset = _read_quality(data, payload, has_flags=wire.has_flags)
        raw = int.from_bytes(data[value_offset : value_offset + wire.value_width], "little", signed=False)
        values.append(CounterValue(index=index, value=raw, quality=quality))
    return values


def _layout_of_kind(block: ObjectBlock, kinds: "frozenset[PointKind]") -> WireLayout | None:
    """The block's wire layout, or None if it has none or reports another kind of point."""
    wire = layout_for(block.header.group, block.header.variation)
    if wire is None or wire.point_kind not in kinds:
        return None
    return wire


_V = TypeVar("_V")


class _Batch(Protocol):
    """Values of one point kind gathered across a response's blocks."""

    def add(self, block: ObjectBlock, wire: WireLayout) -> None:
        """Decode a block into the batch."""

    def deliver(self, handler: SOEHandler, info: ResponseInfo) -> None:
        """Hand the gathered values to the handler, if there are any."""


class _Delivery(Protocol):
    """How one point kind is decoded and delivered."""

    def batch(self) -> _Batch:
        """Start an empty batch for one response."""


@dataclass(frozen=True, slots=True)
class _KindDelivery(Generic[_V]):
    """A point kind's decode function and the handler callback its values go to."""

    decode: "Callable[[ObjectBlock, WireLayout], list[_V]]"
    deliver: "Callable[[SOEHandler, list[_V], ResponseInfo], None]"

    def batch(self) -> "_KindBatch[_V]":
        """Start an empty batch for one response."""
        return _KindBatch(self)


@dataclass(slots=True)
class _KindBatch(Generic[_V]):
    """One response's values for a point kind, in block order."""

    delivery: _KindDelivery[_V]
    values: list[_V] = field(default_factory=list)

    def add(self, block: ObjectBlock, wire: WireLayout) -> None:
        """Decode a block into the batch."""
        self.values.extend(self.delivery.decode(block, wire))

    def deliver(self, handler: SOEHandler, info: ResponseInfo) -> None:
        """Hand the gathered values to the handler, if there are any."""
        if self.values:
            self.delivery.deliver(handler, self.values, info)


# Point kinds the master decodes, in the order their callbacks run for a response.
# A kind absent here (double-bit input, commands, time, class) is framed but not delivered.
_DELIVERIES: Mapping[PointKind, _Delivery] = MappingProxyType(
    {
        PointKind.BINARY_INPUT: _KindDelivery(_decode_binary, lambda h, v, i: h.on_binary_input(v, i)),
        PointKind.BINARY_OUTPUT: _KindDelivery(_decode_binary, lambda h, v, i: h.on_binary_output(v, i)),
        PointKind.ANALOG_INPUT: _KindDelivery(_decode_analog, lambda h, v, i: h.on_analog_input(v, i)),
        PointKind.ANALOG_OUTPUT: _KindDelivery(_decode_analog, lambda h, v, i: h.on_analog_output(v, i)),
        PointKind.COUNTER: _KindDelivery(_decode_counter, lambda h, v, i: h.on_counter(v, i)),
        PointKind.FROZEN_COUNTER: _KindDelivery(_decode_counter, lambda h, v, i: h.on_frozen_counter(v, i)),
    }
)

_BINARY_KINDS = frozenset({PointKind.BINARY_INPUT, PointKind.BINARY_OUTPUT})
_ANALOG_KINDS = frozenset({PointKind.ANALOG_INPUT, PointKind.ANALOG_OUTPUT})
_COUNTER_KINDS = frozenset({PointKind.COUNTER, PointKind.FROZEN_COUNTER})


@dataclass
class Master:
    """DNP3 Master Station implementation.

    Communicates with an outstation to poll data and execute commands.

    Attributes:
        config: Master configuration.
        handler: SOE handler for received data.
    """

    config: MasterConfig = field(default_factory=MasterConfig)
    handler: SOEHandler = field(default_factory=DefaultSOEHandler)
    _state: MasterStateManager = field(default_factory=MasterStateManager, init=False)
    _scheduler: PollScheduler = field(default_factory=PollScheduler, init=False)
    _pending_select: SelectTask | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize master state."""
        self._setup_polling()

    def _setup_polling(self) -> None:
        """Set up polling tasks from config."""
        polling = self.config.polling

        if polling.integrity_poll_interval > 0:
            integrity_task = IntegrityPollTask(interval=polling.integrity_poll_interval)
            self._scheduler.add_task(integrity_task)

        if polling.class_1_poll_interval > 0:
            class1_task = ClassPollTask(class_1=True, interval=polling.class_1_poll_interval)
            self._scheduler.add_task(class1_task)

        if polling.class_2_poll_interval > 0:
            class2_task = ClassPollTask(class_2=True, interval=polling.class_2_poll_interval)
            self._scheduler.add_task(class2_task)

        if polling.class_3_poll_interval > 0:
            class3_task = ClassPollTask(class_3=True, interval=polling.class_3_poll_interval)
            self._scheduler.add_task(class3_task)

    @property
    def state(self) -> MasterState:
        """Get current master state."""
        return self._state.state

    @property
    def is_idle(self) -> bool:
        """Check if master is idle."""
        return self._state.is_idle

    @property
    def scheduler(self) -> PollScheduler:
        """Get the poll scheduler."""
        return self._scheduler

    # -------------------------------------------------------------------------
    # Request Building
    # -------------------------------------------------------------------------

    def build_integrity_poll(self) -> RequestFragment:
        """Build an integrity poll request.

        Returns:
            Request fragment for integrity poll.
        """
        task = IntegrityPollTask()
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_class_poll(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build a class poll request.

        Args:
            class_1: Include Class 1 events.
            class_2: Include Class 2 events.
            class_3: Include Class 3 events.

        Returns:
            Request fragment for class poll.
        """
        task = ClassPollTask(class_1=class_1, class_2=class_2, class_3=class_3)
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_range_poll(
        self,
        group: int,
        variation: int,
        start: int,
        stop: int,
    ) -> RequestFragment:
        """Build a range poll request.

        Args:
            group: Object group.
            variation: Object variation.
            start: Start index.
            stop: Stop index.

        Returns:
            Request fragment for range poll.
        """
        task = RangePollTask(group=group, variation=variation, start=start, stop=stop)
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_select(self, task: SelectTask) -> RequestFragment:
        """Build a SELECT request.

        Args:
            task: Select task with operations.

        Returns:
            Request fragment for SELECT.
        """
        seq = self._state.get_next_request_sequence()
        self._pending_select = task
        return task.build_request(seq=seq)

    def build_operate(self, task: OperateTask) -> RequestFragment:
        """Build an OPERATE request.

        Args:
            task: Operate task with operations.

        Returns:
            Request fragment for OPERATE.
        """
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_direct_operate(self, task: DirectOperateTask) -> RequestFragment:
        """Build a DIRECT_OPERATE request.

        Args:
            task: Direct operate task with operations.

        Returns:
            Request fragment for DIRECT_OPERATE.
        """
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_enable_unsolicited(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build an ENABLE_UNSOLICITED request.

        Args:
            class_1: Enable Class 1.
            class_2: Enable Class 2.
            class_3: Enable Class 3.

        Returns:
            Request fragment for ENABLE_UNSOLICITED.
        """
        seq = self._state.get_next_request_sequence()
        return build_enable_unsolicited_request(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
            seq=seq,
        )

    def build_disable_unsolicited(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build a DISABLE_UNSOLICITED request.

        Args:
            class_1: Disable Class 1.
            class_2: Disable Class 2.
            class_3: Disable Class 3.

        Returns:
            Request fragment for DISABLE_UNSOLICITED.
        """
        seq = self._state.get_next_request_sequence()
        return build_disable_unsolicited_request(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
            seq=seq,
        )

    def build_delay_measure(self) -> RequestFragment:
        """Build a DELAY_MEASURE request.

        Returns:
            Request fragment for DELAY_MEASURE.
        """
        seq = self._state.get_next_request_sequence()
        return build_delay_measure_request(seq=seq)

    def build_confirm(self, seq: int, *, uns: bool = False) -> RequestFragment:
        """Build a CONFIRM request.

        Args:
            seq: Sequence number to confirm.
            uns: Whether the confirmed fragment was unsolicited. A CONFIRM
                echoes the SEQ and UNS of the fragment it answers
                (IEEE 1815-2012 4.2.2.4 Rule 18).

        Returns:
            Request fragment for CONFIRM.
        """
        return RequestFragment(header=RequestHeader.build(function=FunctionCode.CONFIRM, seq=seq, uns=uns))

    # -------------------------------------------------------------------------
    # Response Processing
    # -------------------------------------------------------------------------

    def process_response(self, data: bytes) -> ResponseInfo | None:
        """Process a response from the outstation.

        Args:
            data: Raw response bytes.

        Returns:
            Response info, or None if parse failed.
        """
        try:
            response = parse_response(data)
        except Exception:
            return None

        return self._process_response_fragment(response)

    def _process_response_fragment(self, response: ResponseFragment) -> ResponseInfo:
        """Process a parsed response fragment.

        Args:
            response: Parsed response fragment.

        Returns:
            Response information.
        """
        info = ResponseInfo(
            function=response.header.function,
            iin=response.header.iin,
            sequence=response.header.control.seq,
            is_unsolicited=response.header.control.uns,
            fir=response.header.control.fir,
            fin=response.header.control.fin,
            con=response.header.control.con,
        )

        # Handle unsolicited responses
        if info.is_unsolicited:
            self._state.on_unsolicited_received(info.sequence)

        # Parse data objects and call handler
        self._parse_response_objects(response.objects, info)

        # Update state
        if not info.is_unsolicited and self._state.validate_response_sequence(info.sequence):
            self._state.complete_current_task()

        return info

    def _parse_response_objects(self, objects: Sequence[ObjectBlock], info: ResponseInfo) -> None:
        """Parse response objects and call appropriate handler methods.

        Args:
            objects: Object blocks from response.
            info: Response information.
        """
        batches = {kind: delivery.batch() for kind, delivery in _DELIVERIES.items()}

        for block in objects:
            wire = layout_for(block.header.group, block.header.variation)
            if wire is None:
                continue
            batch = batches.get(wire.point_kind)
            if batch is not None:
                batch.add(block, wire)

        for batch in batches.values():
            batch.deliver(self.handler, info)

    def _parse_binary_values(self, block: ObjectBlock) -> list[BinaryValue]:
        """Parse binary values from object block.

        Args:
            block: Object block containing binary data.

        Returns:
            List of parsed binary values.
        """
        wire = _layout_of_kind(block, _BINARY_KINDS)
        return [] if wire is None else _decode_binary(block, wire)

    def _parse_analog_values(self, block: ObjectBlock) -> list[AnalogValue]:
        """Parse analog values from object block.

        Args:
            block: Object block containing analog data.

        Returns:
            List of parsed analog values.
        """
        wire = _layout_of_kind(block, _ANALOG_KINDS)
        return [] if wire is None else _decode_analog(block, wire)

    def _parse_counter_values(self, block: ObjectBlock) -> list[CounterValue]:
        """Parse counter values from object block.

        Args:
            block: Object block containing counter data.

        Returns:
            List of parsed counter values.
        """
        wire = _layout_of_kind(block, _COUNTER_KINDS)
        return [] if wire is None else _decode_counter(block, wire)

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def command_builder(self) -> CommandBuilder:
        """Get a new command builder.

        Returns:
            New CommandBuilder instance.
        """
        return CommandBuilder()

    def needs_confirm(self) -> bool:
        """Check if an unsolicited confirm is needed.

        Returns:
            True if confirm should be sent.
        """
        return self._state.unsolicited.pending_confirm

    def get_confirm_sequence(self) -> int:
        """Get the sequence number to confirm.

        Returns:
            Sequence number for confirm.
        """
        return self._state.unsolicited.last_sequence

    def on_confirm_sent(self) -> None:
        """Mark that confirm was sent."""
        self._state.on_unsolicited_confirmed()

    def get_next_poll(self) -> PollTask | None:
        """Get the next poll task to execute.

        Returns:
            Next poll task, or None if none due.
        """
        return self._scheduler.get_next_task()

    def mark_poll_executed(self, task: PollTask) -> None:
        """Mark a poll task as executed.

        Args:
            task: Poll task that was executed.
        """
        task.mark_executed()

    def next_request_sequence(self) -> int:
        """Reserve the next application sequence number for an outbound request.

        The `build_*` methods call this internally. It is public so that a
        caller building a request from a `PollTask` (which does its own
        building and takes `seq` as an argument) draws from the same counter,
        instead of numbering scheduled polls separately from direct ones.

        Returns:
            Sequence number to use, 0-15.
        """
        return self._state.get_next_request_sequence()

    def check_timeout(self) -> bool:
        """Check for and handle task timeout.

        Returns:
            True if timeout occurred.
        """
        return self._state.check_task_timeout()
