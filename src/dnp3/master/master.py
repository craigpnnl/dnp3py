"""DNP3 Master Station implementation per IEEE 1815-2012.

The Master class handles communication with an outstation,
including polling, commands, and unsolicited response handling.
"""

import logging
import struct
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Generic, Protocol, TypeVar

from dnp3.application.builder import (
    build_delay_measure_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.parser import ParseError, parse_response
from dnp3.core.enums import FunctionCode
from dnp3.master.commands import (
    CommandBuilder,
    DirectOperateTask,
    OperateTask,
    SelectTask,
)
from dnp3.master.config import MasterConfig
from dnp3.master.double_bit import (
    DOUBLE_BIT_FLAGS_MASK,
    DoubleBitValue,
    deliver_double_bit_input,
    double_bit_state,
    unpack_double_bit_states,
)
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
from dnp3.objects.layout import PointKind, TimeKind, ValueCodec, WireLayout, layout_for

logger = logging.getLogger(__name__)

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
    at the declared count. A block whose data is shorter than its declared count
    yields nothing: an object header carries no length (IEEE 1815-2012 4.2.2.7),
    so no object in it is known to be real.
    """
    entry_width = layout.index_prefix_width + object_width
    offset = layout.data_offset
    ordinal = 0

    if layout.count is not None and offset + layout.count * entry_width > len(data):
        return

    while layout.count is None or ordinal < layout.count:
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


# Epoch for DNP3TIME (IEEE 1815-2012 11.3): a UINT48 count of milliseconds
# since 1970-01-01 00:00:00 UTC.
_DNP3TIME_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _decode_timestamp(raw: bytes) -> datetime | None:
    """Decode a DNP3TIME field (little-endian UINT48 ms since the epoch, 11.3).

    None when the 48-bit count exceeds Python's datetime range (year 9999):
    the wire field permits any UINT48, but no genuine response carries one that
    large, and the index, value and flags of the same object must still be
    delivered rather than lost to an exception from an unusable time field.
    """
    return _after(_DNP3TIME_EPOCH, int.from_bytes(raw, "little", signed=False))


def _after(base: datetime, milliseconds: int) -> datetime | None:
    """`base` plus `milliseconds`, or None past Python's datetime range (year 9999)."""
    try:
        return base + timedelta(milliseconds=milliseconds)
    except OverflowError:
        return None


def _read_timestamp(data: bytes, payload: int, wire: WireLayout, cto: datetime | None) -> datetime | None:
    """Decode a layout's trailing time field, or None when it gives no absolute time.

    The time field is the last `wire.time.octets` octets of the object, after
    any flag octet and value field. A relative time (A.3.3, A.5.3) is a UINT16
    count of milliseconds after `cto`, the preceding common time of occurrence
    in the fragment, and gives None when there is none.
    """
    offset = payload + wire.width - wire.time.octets
    raw = data[offset : offset + wire.time.octets]
    if wire.time is TimeKind.ABSOLUTE:
        return _decode_timestamp(raw)
    if wire.time is TimeKind.RELATIVE and cto is not None:
        return _after(cto, int.from_bytes(raw, "little", signed=False))
    return None


# A.24: group 51 objects are common times of occurrence, the base of later relative times.
_CTO_GROUP = 51


def _common_time_after(block: ObjectBlock, wire: WireLayout, preceding: datetime | None) -> datetime | None:
    """The common time of occurrence in force after a group 51 block.

    A relative time counts from the immediately preceding CTO object (A.24.1), so
    the block's last object replaces `preceding`, and a block of no objects leaves
    it. A block that cannot be read, or whose time is past year 9999, gives None:
    a later relative time must not be counted from a CTO it does not follow.
    """
    slots = _block_slots(block)
    if slots is None:
        return None
    payloads = [payload for _, payload in _iter_object_slots(slots, block.data, wire.width)]
    if not payloads:
        return preceding if slots.count == 0 else None
    return _decode_timestamp(block.data[payloads[-1] : payloads[-1] + wire.width])


def _parse_packed_binary(layout: ObjectLayout, data: bytes) -> list[BinaryValue]:
    """Parse bit-packed binary points (g1v1 / g10v1), 8 points per byte.

    Bounded by the range's declared count so the unused high bits of the final
    byte are not reported as real points. Returns an empty list when the payload
    is too short to hold every declared point, the rule `_iter_object_slots` applies.
    """
    values: list[BinaryValue] = []
    payload = data[layout.data_offset :]
    total = layout.count if layout.count is not None else len(payload) * 8
    if len(payload) < (total + 7) // 8:
        return values

    for ordinal in range(total):
        byte_index, bit = divmod(ordinal, 8)
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


def _decode_binary(block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> list[BinaryValue]:
    """Decode binary input or output points: packed bits, or one flag octet per point.

    A layout with a time field also decodes it into `timestamp`; see `_read_timestamp`.
    """
    slots = _block_slots(block)
    if slots is None:
        return []
    data = block.data
    if wire.is_packed:
        # A.2.1 and A.6.1 pack bits over a contiguous index range; a prefixed block has no bit layout.
        if slots.index_prefix_width:
            return []
        return _parse_packed_binary(slots, data)

    values: list[BinaryValue] = []
    for index, payload in _iter_object_slots(slots, data, wire.width):
        flags = data[payload]
        values.append(
            BinaryValue(
                index=index,
                value=bool(flags & QUALITY_STATE),
                quality=flags & ~QUALITY_STATE,
                timestamp=_read_timestamp(data, payload, wire, cto),
            )
        )
    return values


def _decode_analog(block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> list[AnalogValue]:
    """Decode analog input or output points.

    A layout with a time field also decodes it into `timestamp`; see `_read_timestamp`.
    """
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
                timestamp=_read_timestamp(data, payload, wire, cto),
            )
        )
    return values


def _decode_counter(block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> list[CounterValue]:
    """Decode counter or frozen counter points.

    A layout with a time field also decodes it into `timestamp`; see `_read_timestamp`.
    """
    slots = _block_slots(block)
    if wire.codec is not ValueCodec.UINT or slots is None:
        return []
    data = block.data

    values: list[CounterValue] = []
    for index, payload in _iter_object_slots(slots, data, wire.width):
        quality, value_offset = _read_quality(data, payload, has_flags=wire.has_flags)
        raw = int.from_bytes(data[value_offset : value_offset + wire.value_width], "little", signed=False)
        values.append(
            CounterValue(
                index=index,
                value=raw,
                quality=quality,
                timestamp=_read_timestamp(data, payload, wire, cto),
            )
        )
    return values


def _decode_double_bit(block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> list[DoubleBitValue]:
    """Decode double-bit binary input points: packed states, or one flag octet per point.

    A layout with a time field also decodes it into `timestamp`; see `_read_timestamp`.
    """
    slots = _block_slots(block)
    if slots is None:
        return []
    data = block.data
    if wire.is_packed:
        # A.4.1 packs states over a contiguous index range; a prefixed block has no bit layout.
        # Every range decoded here sets count; the None test only narrows its optional type.
        if slots.index_prefix_width or slots.count is None:
            return []
        states = unpack_double_bit_states(data[slots.data_offset :], slots.count)
        # A.4.1.2.3: packed values carry no flags and are taken as online.
        return [
            DoubleBitValue(index=slots.first_index + ordinal, state=state, quality=QUALITY_ONLINE)
            for ordinal, state in enumerate(states)
        ]

    return [
        DoubleBitValue(
            index=index,
            state=double_bit_state(data[payload]),
            quality=data[payload] & DOUBLE_BIT_FLAGS_MASK,
            timestamp=_read_timestamp(data, payload, wire, cto),
        )
        for index, payload in _iter_object_slots(slots, data, wire.width)
    ]


class _Timed(Protocol):
    """A decoded value, which may carry a timestamp."""

    @property
    def timestamp(self) -> datetime | None:
        """When the value was recorded, if known."""


_V = TypeVar("_V", bound=_Timed)


class _Batch(Protocol):
    """Values of one point kind gathered from one run of consecutive blocks of that kind."""

    def add(self, block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> int:
        """Decode a block into the batch, timing relative objects from `cto`.

        Returns how many of the block's values have no timestamp.
        """

    def deliver(self, handler: SOEHandler, info: ResponseInfo) -> None:
        """Hand the gathered values to the handler, if there are any."""


class _Delivery(Protocol):
    """How one point kind is decoded and delivered."""

    def batch(self) -> _Batch:
        """Start an empty batch for one run of consecutive blocks of this kind."""


@dataclass(frozen=True, slots=True)
class _KindDelivery(Generic[_V]):
    """A point kind's decode function and the handler callback its values go to."""

    decode: Callable[[ObjectBlock, WireLayout, datetime | None], list[_V]]
    deliver: Callable[[SOEHandler, list[_V], ResponseInfo], None]

    def batch(self) -> "_KindBatch[_V]":
        """Start an empty batch for one run of consecutive blocks of this kind."""
        return _KindBatch(self)


@dataclass(slots=True)
class _KindBatch(Generic[_V]):
    """Values of one run of consecutive same-kind blocks in a response, in block order."""

    delivery: _KindDelivery[_V]
    values: list[_V] = field(default_factory=list)

    def add(self, block: ObjectBlock, wire: WireLayout, cto: datetime | None) -> int:
        """Decode a block into the batch, timing relative objects from `cto`.

        Returns how many of the block's values have no timestamp.
        """
        decoded = self.delivery.decode(block, wire, cto)
        self.values.extend(decoded)
        return sum(value.timestamp is None for value in decoded)

    def deliver(self, handler: SOEHandler, info: ResponseInfo) -> None:
        """Hand the gathered values to the handler, if there are any."""
        if self.values:
            self.delivery.deliver(handler, self.values, info)


# Point kinds the master decodes, each with the callback its values go to.
# A kind absent here (commands and command events, frozen analog, deadband, time, class)
# is framed but not delivered. Double-bit values reach only a handler with that callback.
_DELIVERIES: Mapping[PointKind, _Delivery] = MappingProxyType(
    {
        PointKind.BINARY_INPUT: _KindDelivery(_decode_binary, lambda h, v, i: h.on_binary_input(v, i)),
        PointKind.DOUBLE_BIT_INPUT: _KindDelivery(_decode_double_bit, deliver_double_bit_input),
        PointKind.BINARY_OUTPUT: _KindDelivery(_decode_binary, lambda h, v, i: h.on_binary_output(v, i)),
        PointKind.ANALOG_INPUT: _KindDelivery(_decode_analog, lambda h, v, i: h.on_analog_input(v, i)),
        PointKind.ANALOG_OUTPUT: _KindDelivery(_decode_analog, lambda h, v, i: h.on_analog_output(v, i)),
        PointKind.COUNTER: _KindDelivery(_decode_counter, lambda h, v, i: h.on_counter(v, i)),
        PointKind.FROZEN_COUNTER: _KindDelivery(_decode_counter, lambda h, v, i: h.on_frozen_counter(v, i)),
    }
)


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
            Response info, or None if the parser's own ParseError signaled
            a malformed fragment.

        Raises:
            Exception: Anything the parser raises besides ParseError
                propagates to the caller.
        """
        try:
            response = parse_response(data)
        except ParseError as exc:
            logger.warning("Failed to parse response (%d bytes): %s", len(data), exc)
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
            truncation=response.truncation,
        )

        truncation = response.truncation
        if truncation is not None:
            # An unsolicited fragment's info reaches no caller of request(), so this may be its only trace.
            qualifier = "None" if truncation.qualifier is None else f"0x{truncation.qualifier:02X}"
            logger.warning(
                "Response fragment seq=%d unsolicited=%s cut short (%s) at object offset %d: "
                "group %s, variation %s, qualifier %s; no value from that block onward was delivered",
                info.sequence,
                info.is_unsolicited,
                truncation.reason.value,
                truncation.offset,
                truncation.group,
                truncation.variation,
                qualifier,
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
        """Parse response objects and call appropriate handler methods, in fragment order.

        IEEE 1815-2012 5.1.5.1.3: the master processes objects in the order they appear
        in the fragment. Consecutive blocks of one point kind share one callback; a block
        of another delivered kind ends that run, and a block with no delivery is skipped
        without ending it.

        A block of another kind ends a run even when the handler lacks that kind's callback.
        A block that decodes to no values still ends a run of another kind.

        A relative-time object is timed from the last common time of occurrence (group 51)
        before it in this fragment, since each fragment is parsed on its own (4.3 Rule 7).
        It has no timestamp when there is none, or when the time falls past year 9999;
        either way it is counted in `info.relative_time_without_cto`. A CTO block does
        not end a run.

        Args:
            objects: Object blocks from response.
            info: Response information.
        """
        run_kind: PointKind | None = None
        run: _Batch | None = None
        cto: datetime | None = None

        for block in objects:
            wire = layout_for(block.header.group, block.header.variation)
            if wire is None:
                continue
            if block.header.group == _CTO_GROUP:
                cto = _common_time_after(block, wire, cto)
                continue
            delivery = _DELIVERIES.get(wire.point_kind)
            if delivery is None:
                continue
            if run is None or wire.point_kind is not run_kind:
                if run is not None:
                    run.deliver(self.handler, info)
                run_kind = wire.point_kind
                run = delivery.batch()
            untimed = run.add(block, wire, cto)
            if wire.time is TimeKind.RELATIVE:
                info.relative_time_without_cto += untimed

        if run is not None:
            run.deliver(self.handler, info)

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
