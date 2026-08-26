"""DNP3 Master Station implementation per IEEE 1815-2012.

The Master class handles communication with an outstation,
including polling, commands, and unsolicited response handling.
"""

import struct
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from dnp3.application.builder import (
    build_confirm_request,
    build_delay_measure_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.parser import parse_response
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

# Variation 1 of groups 1 and 10 is bit-packed. Other variations are resolved
# through the per-group width and spec tables below, which is why there is no
# flat VARIATION_* set here: the same variation number means different layouts
# in different groups (g30v1 is a 32-bit value, g1v1 is packed bits), and a
# single table keyed on the number alone is what made event blocks misparse.
VARIATION_PACKED = 1


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


# Groups whose variation 1 is genuinely bit-packed (1 bit per point). Event
# groups (2, 11, 22, 32, 42) also number a variation 1, but it is one flags byte
# per point, so packed decoding must be keyed on the group as well.
PACKED_FORMAT_GROUPS = frozenset({GROUP_BINARY_INPUT, GROUP_BINARY_OUTPUT})

# Per-object widths in bytes for binary variations, excluding any index prefix.
_BINARY_FLAGS_WIDTH = 1
_ABSOLUTE_TIMESTAMP_WIDTH = 6
_RELATIVE_TIME_WIDTH = 2

# Static groups 1 and 10: variation 2 is a bare flags byte.
_STATIC_BINARY_WIDTHS = {
    2: _BINARY_FLAGS_WIDTH,
}

# Event groups 2 and 11: variation 1 is a bare flags byte, 2 appends a 48-bit
# absolute timestamp, 3 appends a 16-bit time relative to the fragment's CTO.
_EVENT_BINARY_WIDTHS = {
    1: _BINARY_FLAGS_WIDTH,
    2: _BINARY_FLAGS_WIDTH + _ABSOLUTE_TIMESTAMP_WIDTH,
    3: _BINARY_FLAGS_WIDTH + _RELATIVE_TIME_WIDTH,
}

_BINARY_EVENT_GROUPS = frozenset({GROUP_BINARY_INPUT_EVENT, GROUP_BINARY_OUTPUT_EVENT})


def _binary_object_width(group: int, variation: int) -> int | None:
    """Per-object width for a binary group/variation, or None if unsupported.

    Resolved per group because variation 2 means different things either side of
    the static/event split: a bare flags byte for g1v2/g10v2, but flags plus a
    48-bit timestamp for g2v2/g11v2.
    """
    if group in _BINARY_EVENT_GROUPS:
        return _EVENT_BINARY_WIDTHS.get(variation)
    return _STATIC_BINARY_WIDTHS.get(variation)


def _decode_signed_int(raw: bytes) -> float:
    """Decode a little-endian signed integer as a float."""
    return float(int.from_bytes(raw, "little", signed=True))


def _decode_float32(raw: bytes) -> float:
    """Decode a little-endian IEEE 754 single-precision value."""
    return float(struct.unpack("<f", raw)[0])


def _decode_float64(raw: bytes) -> float:
    """Decode a little-endian IEEE 754 double-precision value."""
    return float(struct.unpack("<d", raw)[0])


@dataclass(frozen=True, slots=True)
class AnalogValueSpec:
    """How to decode one analog object.

    Attributes:
        value_width: Bytes of value payload.
        has_flags: Whether a quality flags byte precedes the value.
        decode: Converts the value bytes to a float.
        timestamp_width: Bytes of trailing timestamp to skip.
    """

    value_width: int
    has_flags: bool
    decode: "Callable[[bytes], float]"
    timestamp_width: int = 0

    @property
    def object_width(self) -> int:
        """Total bytes per object, excluding any index prefix."""
        flags_width = 1 if self.has_flags else 0
        return flags_width + self.value_width + self.timestamp_width


@dataclass(frozen=True, slots=True)
class CounterValueSpec:
    """How to decode one counter object."""

    value_width: int
    has_flags: bool
    timestamp_width: int = 0

    @property
    def object_width(self) -> int:
        """Total bytes per object, excluding any index prefix."""
        flags_width = 1 if self.has_flags else 0
        return flags_width + self.value_width + self.timestamp_width


# Static analog input/output variations (groups 30, 40).
_STATIC_ANALOG_SPECS = {
    1: AnalogValueSpec(value_width=4, has_flags=True, decode=_decode_signed_int),
    2: AnalogValueSpec(value_width=2, has_flags=True, decode=_decode_signed_int),
    3: AnalogValueSpec(value_width=4, has_flags=False, decode=_decode_signed_int),
    4: AnalogValueSpec(value_width=2, has_flags=False, decode=_decode_signed_int),
    5: AnalogValueSpec(value_width=4, has_flags=True, decode=_decode_float32),
    6: AnalogValueSpec(value_width=8, has_flags=True, decode=_decode_float64),
}

# Analog event variations (groups 32, 42). Variations 3, 4, 7 and 8 repeat
# 1, 2, 5 and 6 with a 48-bit timestamp appended.
_EVENT_ANALOG_SPECS = {
    1: AnalogValueSpec(value_width=4, has_flags=True, decode=_decode_signed_int),
    2: AnalogValueSpec(value_width=2, has_flags=True, decode=_decode_signed_int),
    3: AnalogValueSpec(
        value_width=4,
        has_flags=True,
        decode=_decode_signed_int,
        timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH,
    ),
    4: AnalogValueSpec(
        value_width=2,
        has_flags=True,
        decode=_decode_signed_int,
        timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH,
    ),
    5: AnalogValueSpec(value_width=4, has_flags=True, decode=_decode_float32),
    6: AnalogValueSpec(value_width=8, has_flags=True, decode=_decode_float64),
    7: AnalogValueSpec(
        value_width=4,
        has_flags=True,
        decode=_decode_float32,
        timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH,
    ),
    8: AnalogValueSpec(
        value_width=8,
        has_flags=True,
        decode=_decode_float64,
        timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH,
    ),
}

# Static counter variations (groups 20, 21).
_STATIC_COUNTER_SPECS = {
    1: CounterValueSpec(value_width=4, has_flags=True),
    2: CounterValueSpec(value_width=2, has_flags=True),
    5: CounterValueSpec(value_width=4, has_flags=False),
    6: CounterValueSpec(value_width=2, has_flags=False),
}

# Counter event variations (group 22). 5 and 6 add a 48-bit timestamp.
_EVENT_COUNTER_SPECS = {
    1: CounterValueSpec(value_width=4, has_flags=True),
    2: CounterValueSpec(value_width=2, has_flags=True),
    5: CounterValueSpec(value_width=4, has_flags=True, timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH),
    6: CounterValueSpec(value_width=2, has_flags=True, timestamp_width=_ABSOLUTE_TIMESTAMP_WIDTH),
}


def _analog_value_spec(group: int, variation: int) -> AnalogValueSpec | None:
    """Look up the decoding spec for an analog group/variation, or None."""
    if group in {GROUP_ANALOG_INPUT_EVENT, GROUP_ANALOG_OUTPUT_EVENT}:
        return _EVENT_ANALOG_SPECS.get(variation)
    return _STATIC_ANALOG_SPECS.get(variation)


def _counter_value_spec(group: int, variation: int) -> CounterValueSpec | None:
    """Look up the decoding spec for a counter group/variation, or None."""
    if group == GROUP_COUNTER_EVENT:
        return _EVENT_COUNTER_SPECS.get(variation)
    return _STATIC_COUNTER_SPECS.get(variation)


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

    def build_confirm(self, seq: int) -> RequestFragment:
        """Build a CONFIRM request.

        Args:
            seq: Sequence number to confirm.

        Returns:
            Request fragment for CONFIRM.
        """
        return build_confirm_request(seq=seq)

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
        binary_inputs: list[BinaryValue] = []
        binary_outputs: list[BinaryValue] = []
        analog_inputs: list[AnalogValue] = []
        analog_outputs: list[AnalogValue] = []
        counters: list[CounterValue] = []
        frozen_counters: list[CounterValue] = []

        for block in objects:
            group = block.header.group

            if group in {GROUP_BINARY_INPUT, GROUP_BINARY_INPUT_EVENT}:
                binary_inputs.extend(self._parse_binary_values(block))
            elif group in {GROUP_BINARY_OUTPUT, GROUP_BINARY_OUTPUT_EVENT}:
                binary_outputs.extend(self._parse_binary_values(block))
            elif group in {GROUP_ANALOG_INPUT, GROUP_ANALOG_INPUT_EVENT}:
                analog_inputs.extend(self._parse_analog_values(block))
            elif group in {GROUP_ANALOG_OUTPUT, GROUP_ANALOG_OUTPUT_EVENT}:
                analog_outputs.extend(self._parse_analog_values(block))
            elif group in {GROUP_COUNTER, GROUP_COUNTER_EVENT}:
                counters.extend(self._parse_counter_values(block))
            elif group == GROUP_FROZEN_COUNTER:
                frozen_counters.extend(self._parse_counter_values(block))

        # Call handler methods
        if binary_inputs:
            self.handler.on_binary_input(binary_inputs, info)
        if binary_outputs:
            self.handler.on_binary_output(binary_outputs, info)
        if analog_inputs:
            self.handler.on_analog_input(analog_inputs, info)
        if analog_outputs:
            self.handler.on_analog_output(analog_outputs, info)
        if counters:
            self.handler.on_counter(counters, info)
        if frozen_counters:
            self.handler.on_frozen_counter(frozen_counters, info)

    def _parse_binary_values(self, block: ObjectBlock) -> list[BinaryValue]:
        """Parse binary values from object block.

        Args:
            block: Object block containing binary data.

        Returns:
            List of parsed binary values.
        """
        data = block.data
        if not data:
            return []

        header = block.header
        layout = _decode_object_layout(header.qualifier, data)
        if layout is None:
            return []

        # Packed format is group 1 variation 1 only (and group 10 variation 1 for
        # outputs). Event groups also number their first variation 1, but it is
        # one flags byte per point, so keying off variation alone would decode
        # every event block as bit-packed and fabricate points.
        if header.variation == VARIATION_PACKED and header.group in PACKED_FORMAT_GROUPS:
            return _parse_packed_binary(layout, data)

        object_width = _binary_object_width(header.group, header.variation)
        if object_width is None:
            return []

        values: list[BinaryValue] = []
        for index, payload in _iter_object_slots(layout, data, object_width):
            flags = data[payload]
            values.append(
                BinaryValue(
                    index=index,
                    value=bool(flags & QUALITY_STATE),
                    quality=flags & ~QUALITY_STATE,
                )
            )
        return values

    def _parse_analog_values(self, block: ObjectBlock) -> list[AnalogValue]:
        """Parse analog values from object block.

        Args:
            block: Object block containing analog data.

        Returns:
            List of parsed analog values.
        """
        data = block.data
        if not data:
            return []

        header = block.header
        spec = _analog_value_spec(header.group, header.variation)
        if spec is None:
            return []

        layout = _decode_object_layout(header.qualifier, data)
        if layout is None:
            return []

        values: list[AnalogValue] = []
        for index, payload in _iter_object_slots(layout, data, spec.object_width):
            quality, value_offset = _read_quality(data, payload, has_flags=spec.has_flags)
            values.append(
                AnalogValue(
                    index=index,
                    value=spec.decode(data[value_offset : value_offset + spec.value_width]),
                    quality=quality,
                )
            )
        return values

    def _parse_counter_values(self, block: ObjectBlock) -> list[CounterValue]:
        """Parse counter values from object block.

        Args:
            block: Object block containing counter data.

        Returns:
            List of parsed counter values.
        """
        data = block.data
        if not data:
            return []

        header = block.header
        spec = _counter_value_spec(header.group, header.variation)
        if spec is None:
            return []

        layout = _decode_object_layout(header.qualifier, data)
        if layout is None:
            return []

        values: list[CounterValue] = []
        for index, payload in _iter_object_slots(layout, data, spec.object_width):
            quality, value_offset = _read_quality(data, payload, has_flags=spec.has_flags)
            raw = int.from_bytes(data[value_offset : value_offset + spec.value_width], "little", signed=False)
            values.append(CounterValue(index=index, value=raw, quality=quality))
        return values

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

    def check_timeout(self) -> bool:
        """Check for and handle task timeout.

        Returns:
            True if timeout occurred.
        """
        return self._state.check_task_timeout()
