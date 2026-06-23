"""DNP3 Outstation implementation per IEEE 1815-2012.

The Outstation class handles incoming requests from a master station,
processes them according to the DNP3 protocol, and generates responses.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dnp3.application.builder import (
    build_null_response,
    build_response,
    build_unsolicited_response,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.parser import parse_request
from dnp3.application.qualifiers import (
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
)
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.core.flags import IIN, BinaryQuality
from dnp3.database import Database, EventClass
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandHandler, DefaultCommandHandler
from dnp3.outstation.state import (
    OutstationState,
    OutstationStateManager,
    SelectState,
)

# Group/Variation constants for response building
GV_BINARY_INPUT_FLAGS = (1, 2)  # g1v2 - Binary Input with flags
GV_BINARY_OUTPUT_FLAGS = (10, 2)  # g10v2 - Binary Output with flags
GV_ANALOG_INPUT_32 = (30, 1)  # g30v1 - 32-bit Analog Input with flags
GV_COUNTER_32 = (20, 1)  # g20v1 - 32-bit Counter with flags
GV_FROZEN_COUNTER_32 = (21, 1)  # g21v1 - 32-bit Frozen Counter with flags
GV_TIME_DELAY = (52, 2)  # g52v2 - Time Delay Fine

# Binary event variations
GV_BINARY_INPUT_EVENT = (2, 1)  # g2v1 - Binary Input Event without time
GV_BINARY_OUTPUT_EVENT = (11, 1)  # g11v1 - Binary Output Event without time

# Analog event variations
GV_ANALOG_INPUT_EVENT = (32, 1)  # g32v1 - 32-bit Analog Event without time

# Counter event variations
GV_COUNTER_EVENT = (22, 1)  # g22v1 - 32-bit Counter Event without time

# CROB group/variation
GV_CROB = (12, 1)  # g12v1 - Control Relay Output Block

# DNP3 group numbers
GROUP_BINARY_INPUT = 1
GROUP_BINARY_INPUT_EVENT = 2
GROUP_BINARY_OUTPUT = 10
GROUP_BINARY_OUTPUT_EVENT = 11
GROUP_CROB = 12
GROUP_COUNTER = 20
GROUP_FROZEN_COUNTER = 21
GROUP_COUNTER_EVENT = 22
GROUP_ANALOG_INPUT = 30
GROUP_ANALOG_INPUT_EVENT = 32
GROUP_CLASS_DATA = 60

# DNP3 class data variations
VAR_CLASS_0 = 1
VAR_CLASS_1 = 2
VAR_CLASS_2 = 3
VAR_CLASS_3 = 4

# Index size thresholds
MAX_1_BYTE_INDEX = 255  # 0xFF
MAX_2_BYTE_INDEX = 65535  # 0xFFFF

# CROB qualifier codes (IEEE 1815-2012 Table 4-3)
# 0x17: 1-byte count field + 1-byte index prefix per object
# 0x28: 2-byte count field + 2-byte index prefix per object
QUALIFIER_CROB_1BYTE = 0x17
QUALIFIER_CROB_2BYTE = 0x28

# CROB body size in bytes: control_code(1) + op_count(1) + on_time(4) + off_time(4) + status(1)
_CROB_BODY_BYTES = 11


def _serialize_binary_input(value: bool, quality: BinaryQuality) -> bytes:
    """Serialize a binary input point to g1v2 format."""
    flags = int(quality)
    if value:
        flags |= BinaryQuality.STATE
    return bytes([flags])


def _serialize_binary_output(value: bool, quality: BinaryQuality) -> bytes:
    """Serialize a binary output point to g10v2 format."""
    flags = int(quality)
    if value:
        flags |= BinaryQuality.STATE
    return bytes([flags])


def _serialize_analog_input_32(value: float, quality: int) -> bytes:
    """Serialize an analog input point to g30v1 format."""
    # 1 byte flags + 4 bytes value (little-endian signed)
    int_value = int(value)
    return bytes([quality]) + int_value.to_bytes(4, byteorder="little", signed=True)


def _serialize_counter_32(value: int, quality: int) -> bytes:
    """Serialize a counter point to g20v1 format."""
    # 1 byte flags + 4 bytes value (little-endian unsigned)
    return bytes([quality]) + value.to_bytes(4, byteorder="little", signed=False)


def _contiguous_runs(points: list[Any]) -> list[list[Any]]:
    """Split a list of points (sorted by index) into contiguous index runs.

    The database holds points in a sparse dict keyed by index; callers MUST NOT
    assume the list is dense (e.g. indices [0, 5, 10] have gaps at 1-4 and 6-9).
    A start/stop range header [0..10] would imply values for the missing indices,
    so each gap-free run must be encoded as its own ObjectBlock.

    Args:
        points: List of points sorted by ascending index (guaranteed by the
            database's get_all_* methods which use sorted(dict.items())).

    Returns:
        A list of one or more non-empty sub-lists, each a contiguous run.
    """
    if not points:
        return []
    runs: list[list[Any]] = [[points[0]]]
    for point in points[1:]:
        if point.index == runs[-1][-1].index + 1:
            runs[-1].append(point)
        else:
            runs.append([point])
    return runs


def _build_static_blocks(
    group: int,
    variation: int,
    points: list[Any],
    serialize: Callable[[Any], bytes],
) -> list[ObjectBlock]:
    """Build ObjectBlocks for static data using start/stop range qualifiers.

    Splits the point list into contiguous index runs first.  Each run becomes
    one ObjectBlock with the correct start/stop range header and no per-object
    index prefix, conforming to IEEE 1815-2012 Table 4-2.

    Args:
        group: Object group number.
        variation: Object variation number.
        points: Sorted list of points (may be sparse).
        serialize: Callable that converts a single point to its wire bytes.

    Returns:
        One ObjectBlock per contiguous run, in index order.
    """
    blocks: list[ObjectBlock] = []
    for run in _contiguous_runs(points):
        header, range_data = _build_start_stop_header(
            group=group,
            variation=variation,
            start=run[0].index,
            stop=run[-1].index,
        )
        data = bytearray()
        for point in run:
            data.extend(serialize(point))
        blocks.append(ObjectBlock(header=header, data=range_data + bytes(data)))
    return blocks


def _crob_count_index_sizes(qualifier: int) -> tuple[int, int]:
    """Return (count_bytes, index_bytes) for a CROB qualifier.

    IEEE 1815-2012 Table 4-3:
      0x17 => 1-byte count, 1-byte index prefix per object
      0x28 => 2-byte count, 2-byte index prefix per object

    Args:
        qualifier: The qualifier byte from the object header.

    Returns:
        A tuple of (count_bytes, index_bytes).

    Raises:
        ValueError: If the qualifier is not 0x17 or 0x28.
    """
    if qualifier == QUALIFIER_CROB_1BYTE:
        return 1, 1
    if qualifier == QUALIFIER_CROB_2BYTE:
        return 2, 2
    msg = f"Unsupported CROB qualifier 0x{qualifier:02X}; expected 0x17 or 0x28"
    raise ValueError(msg)


def _build_start_stop_header(
    group: int,
    variation: int,
    start: int,
    stop: int,
) -> tuple[ObjectHeader, bytes]:
    """Build object header with start-stop range."""
    if stop <= MAX_1_BYTE_INDEX:
        range_code = RangeCode.UINT8_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_1()
    elif stop <= MAX_2_BYTE_INDEX:
        range_code = RangeCode.UINT16_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_2()
    else:
        range_code = RangeCode.UINT32_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_4()

    header = ObjectHeader.build(
        group=group,
        variation=variation,
        prefix=PrefixCode.NONE,
        range_code=range_code,
    )
    return header, range_data


def _build_indexed_header(
    group: int,
    variation: int,
    count: int,
    max_index: int,
) -> ObjectHeader:
    """Build object header with count and index prefix."""
    if max_index <= MAX_1_BYTE_INDEX:
        qualifier = 0x17  # 1-byte count, 1-byte index prefix
    elif max_index <= MAX_2_BYTE_INDEX:
        qualifier = 0x28  # 2-byte count, 2-byte index prefix
    else:
        qualifier = 0x39  # 4-byte count, 4-byte index prefix

    return ObjectHeader(group=group, variation=variation, qualifier=qualifier)


@dataclass(frozen=True)
class ParsedCrob:
    """One parsed CROB object from a received request block.

    When ``control_code`` is None, ``status`` is FORMAT_ERROR (undefined
    control-code nibble, truncated buffer, or unknown qualifier).  Callers
    must check ``status`` before accessing ``control_code``.

    Attributes:
        index: Point index addressed by this CROB.
        control_code: Parsed control code, or None for a FORMAT_ERROR entry.
        op_count: Operation count field.
        on_time: On-time in milliseconds.
        off_time: Off-time in milliseconds.
        status: FORMAT_ERROR or SUCCESS sentinel (callers apply real status).
    """

    index: int
    control_code: ControlCode | None
    op_count: int
    on_time: int
    off_time: int
    status: CommandStatus


def _parse_crob_block(block: ObjectBlock) -> list[ParsedCrob]:
    """Parse a CROB ObjectBlock into a list of ParsedCrob entries.

    Centralises qualifier sizing, count-field reading, per-object index and
    CROB-body parsing, and all three FORMAT_ERROR paths:
      - Unknown qualifier (not 0x17 or 0x28)
      - Buffer too short for the declared count
      - Undefined control-code nibble (0x05-0x0F not in ControlCode enum)

    A malformed entry is represented as a ParsedCrob with
    control_code=None and status=FORMAT_ERROR so the callers never raise.

    Args:
        block: CROB ObjectBlock from a SELECT, OPERATE, or DIRECT_OPERATE request.

    Returns:
        List of ParsedCrob entries (may contain FORMAT_ERROR sentinels).
    """
    data = block.data
    if len(data) < 1:
        return []

    try:
        count_bytes, index_bytes = _crob_count_index_sizes(block.header.qualifier)
    except ValueError:
        return [
            ParsedCrob(index=0, control_code=None, op_count=0, on_time=0, off_time=0, status=CommandStatus.FORMAT_ERROR)
        ]

    if len(data) < count_bytes:
        return [
            ParsedCrob(index=0, control_code=None, op_count=0, on_time=0, off_time=0, status=CommandStatus.FORMAT_ERROR)
        ]

    count = int.from_bytes(data[0:count_bytes], "little")
    offset = count_bytes
    parsed: list[ParsedCrob] = []

    for _ in range(count):
        if offset + index_bytes + _CROB_BODY_BYTES > len(data):
            parsed.append(
                ParsedCrob(
                    index=0, control_code=None, op_count=0, on_time=0, off_time=0, status=CommandStatus.FORMAT_ERROR
                )
            )
            break

        index = int.from_bytes(data[offset : offset + index_bytes], "little")
        offset += index_bytes

        try:
            control_code: ControlCode | None = ControlCode(data[offset] & 0x0F)
        except ValueError:
            parsed.append(
                ParsedCrob(
                    index=index,
                    control_code=None,
                    op_count=0,
                    on_time=0,
                    off_time=0,
                    status=CommandStatus.FORMAT_ERROR,
                )
            )
            offset += _CROB_BODY_BYTES
            continue

        op_count = data[offset + 1]
        on_time = int.from_bytes(data[offset + 2 : offset + 6], "little")
        off_time = int.from_bytes(data[offset + 6 : offset + 10], "little")
        offset += _CROB_BODY_BYTES

        parsed.append(
            ParsedCrob(
                index=index,
                control_code=control_code,
                op_count=op_count,
                on_time=on_time,
                off_time=off_time,
                status=CommandStatus.SUCCESS,
            )
        )

    return parsed


@dataclass
class Outstation:
    """DNP3 Outstation implementation.

    Processes requests from a master station and generates responses.
    Uses a Database for point storage and event generation.

    Attributes:
        config: Outstation configuration.
        database: Point database.
        handler: Command handler for control operations.
    """

    config: OutstationConfig = field(default_factory=OutstationConfig)
    database: Database = field(default_factory=Database)
    handler: CommandHandler = field(default_factory=DefaultCommandHandler)
    _state: OutstationStateManager = field(default_factory=OutstationStateManager, init=False)

    def __post_init__(self) -> None:
        """Initialize outstation state."""
        if self.config.time_sync_required:
            self._state.set_need_time()

    @property
    def state(self) -> OutstationState:
        """Get current outstation state."""
        return self._state.state

    @property
    def iin(self) -> IIN:
        """Get current IIN flags."""
        self._update_event_iin()
        return self._state.get_current_iin()

    def _update_event_iin(self) -> None:
        """Update IIN event flags from event buffer."""
        buffer = self.database.event_buffer
        self._state.update_event_flags(
            class_1_events=buffer.class1.count > 0,
            class_2_events=buffer.class2.count > 0,
            class_3_events=buffer.class3.count > 0,
        )
        if buffer.has_overflow:
            self._state.set_event_overflow()

    def process_request(self, data: bytes) -> ResponseFragment | None:
        """Process a request and generate a response.

        Args:
            data: Raw request bytes (application layer fragment).

        Returns:
            Response fragment, or None if no response needed.
        """
        try:
            request = parse_request(data)
        except Exception:
            # Parse error - return null response with PARAMETER_ERROR
            return build_null_response(iin=self.iin | IIN.PARAMETER_ERROR)

        return self._process_request_fragment(request)

    def _process_request_fragment(self, request: RequestFragment) -> ResponseFragment | None:
        """Process a parsed request fragment.

        Args:
            request: Parsed request fragment.

        Returns:
            Response fragment, or None if no response needed.
        """
        header = request.header
        function = header.function

        # Track request sequence
        self._state.sequences.last_request_seq = header.control.seq

        # Dispatch based on function code
        if function == FunctionCode.READ:
            return self._handle_read(request)
        if function == FunctionCode.WRITE:
            return self._handle_write(request)
        if function == FunctionCode.SELECT:
            return self._handle_select(request)
        if function == FunctionCode.OPERATE:
            return self._handle_operate(request)
        if function == FunctionCode.DIRECT_OPERATE:
            return self._handle_direct_operate(request)
        if function == FunctionCode.DIRECT_OPERATE_NO_ACK:
            self._handle_direct_operate(request)
            return None  # No response for NO_ACK
        if function == FunctionCode.COLD_RESTART:
            return self._handle_cold_restart(request)
        if function == FunctionCode.WARM_RESTART:
            return self._handle_warm_restart(request)
        if function == FunctionCode.DELAY_MEASURE:
            return self._handle_delay_measure(request)
        if function == FunctionCode.ENABLE_UNSOLICITED:
            return self._handle_enable_unsolicited(request)
        if function == FunctionCode.DISABLE_UNSOLICITED:
            return self._handle_disable_unsolicited(request)
        if function == FunctionCode.CONFIRM:
            return self._handle_confirm(request)
        if function == FunctionCode.IMMEDIATE_FREEZE:
            return self._handle_freeze(request, clear=False)
        if function == FunctionCode.FREEZE_CLEAR:
            return self._handle_freeze(request, clear=True)

        # Unsupported function code
        return build_null_response(
            iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
            seq=header.control.seq,
        )

    def _handle_read(self, request: RequestFragment) -> ResponseFragment:
        """Handle READ request."""
        objects: list[ObjectBlock] = []
        error_iin = IIN(0)

        for block in request.objects:
            group = block.header.group
            variation = block.header.variation

            # Handle class data requests (Group 60)
            if group == GROUP_CLASS_DATA:
                class_objects, class_error = self._read_class_data(variation)
                objects.extend(class_objects)
                error_iin |= class_error
            # Binary Inputs (Group 1)
            elif group == GROUP_BINARY_INPUT:
                bi_objects, bi_error = self._read_binary_inputs(block)
                objects.extend(bi_objects)
                error_iin |= bi_error
            # Binary Input Events (Group 2)
            elif group == GROUP_BINARY_INPUT_EVENT:
                event_objects = self._read_binary_input_events()
                objects.extend(event_objects)
            # Binary Outputs (Group 10)
            elif group == GROUP_BINARY_OUTPUT:
                bo_objects, bo_error = self._read_binary_outputs(block)
                objects.extend(bo_objects)
                error_iin |= bo_error
            # Analog Inputs (Group 30)
            elif group == GROUP_ANALOG_INPUT:
                ai_objects, ai_error = self._read_analog_inputs(block)
                objects.extend(ai_objects)
                error_iin |= ai_error
            # Analog Input Events (Group 32)
            elif group == GROUP_ANALOG_INPUT_EVENT:
                event_objects = self._read_analog_input_events()
                objects.extend(event_objects)
            # Counters (Group 20)
            elif group == GROUP_COUNTER:
                ctr_objects, ctr_error = self._read_counters(block)
                objects.extend(ctr_objects)
                error_iin |= ctr_error
            # Counter Events (Group 22)
            elif group == GROUP_COUNTER_EVENT:
                event_objects = self._read_counter_events()
                objects.extend(event_objects)
            # Frozen Counters (Group 21)
            elif group == GROUP_FROZEN_COUNTER:
                fc_objects, fc_error = self._read_frozen_counters(block)
                objects.extend(fc_objects)
                error_iin |= fc_error
            else:
                error_iin |= IIN.OBJECT_UNKNOWN

        return build_response(
            objects=tuple(objects),
            iin=self.iin | error_iin,
            seq=request.header.control.seq,
        )

    def _read_class_data(self, variation: int) -> tuple[list[ObjectBlock], IIN]:
        """Read class data (Group 60).

        Args:
            variation: Class variation (1=Class 0, 2=Class 1, 3=Class 2, 4=Class 3).

        Returns:
            Tuple of (object blocks, error IIN).
        """
        objects: list[ObjectBlock] = []

        if variation == VAR_CLASS_0:  # Class 0 - all static data
            objects.extend(self._read_all_static_data())
        elif variation == VAR_CLASS_1:  # Class 1 events
            objects.extend(self._read_class_events(EventClass.CLASS_1))
        elif variation == VAR_CLASS_2:  # Class 2 events
            objects.extend(self._read_class_events(EventClass.CLASS_2))
        elif variation == VAR_CLASS_3:  # Class 3 events
            objects.extend(self._read_class_events(EventClass.CLASS_3))
        else:
            return [], IIN.OBJECT_UNKNOWN

        return objects, IIN(0)

    def _read_all_static_data(self) -> list[ObjectBlock]:
        """Read all static data (Class 0)."""
        objects: list[ObjectBlock] = []

        # Binary Inputs
        bi_points = self.database.get_all_binary_inputs()
        if bi_points:
            objects.extend(self._build_binary_input_blocks(bi_points))

        # Binary Outputs
        bo_points = self.database.get_all_binary_outputs()
        if bo_points:
            objects.extend(self._build_binary_output_blocks(bo_points))

        # Analog Inputs
        ai_points = self.database.get_all_analog_inputs()
        if ai_points:
            objects.extend(self._build_analog_input_blocks(ai_points))

        # Counters
        ctr_points = self.database.get_all_counters()
        if ctr_points:
            objects.extend(self._build_counter_blocks(ctr_points))

        # Frozen Counters
        fc_points = self.database.get_all_frozen_counters()
        if fc_points:
            objects.extend(self._build_frozen_counter_blocks(fc_points))

        return objects

    def _build_binary_input_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build ObjectBlocks for binary input static data.

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GV_BINARY_INPUT_FLAGS[0],
            variation=GV_BINARY_INPUT_FLAGS[1],
            points=points,
            serialize=lambda p: _serialize_binary_input(p.value, p.quality),
        )

    def _build_binary_output_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build ObjectBlocks for binary output static data.

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GV_BINARY_OUTPUT_FLAGS[0],
            variation=GV_BINARY_OUTPUT_FLAGS[1],
            points=points,
            serialize=lambda p: _serialize_binary_output(p.value, p.quality),
        )

    def _build_analog_input_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build ObjectBlocks for analog input static data.

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GV_ANALOG_INPUT_32[0],
            variation=GV_ANALOG_INPUT_32[1],
            points=points,
            serialize=lambda p: _serialize_analog_input_32(p.value, int(p.quality)),
        )

    def _build_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build ObjectBlocks for counter static data.

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GV_COUNTER_32[0],
            variation=GV_COUNTER_32[1],
            points=points,
            serialize=lambda p: _serialize_counter_32(p.value, int(p.quality)),
        )

    def _build_frozen_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build ObjectBlocks for frozen counter static data.

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GV_FROZEN_COUNTER_32[0],
            variation=GV_FROZEN_COUNTER_32[1],
            points=points,
            serialize=lambda p: _serialize_counter_32(p.value, int(p.quality)),
        )

    def _read_class_events(self, event_class: EventClass) -> list[ObjectBlock]:
        """Read and clear events for a class."""
        objects: list[ObjectBlock] = []
        buffer = self.database.event_buffer

        # Read and clear events
        events = buffer.pop_class_events(event_class)

        # Group events by type and build blocks
        # For simplicity, we build one block per event type
        binary_events = [e for e in events if hasattr(e, "value") and isinstance(e.value, bool)]
        analog_events = [e for e in events if hasattr(e, "value") and isinstance(e.value, float)]
        counter_events = [e for e in events if hasattr(e, "value") and isinstance(e.value, int)]

        if binary_events:
            objects.extend(self._build_binary_event_blocks(binary_events))
        if analog_events:
            objects.extend(self._build_analog_event_blocks(analog_events))
        if counter_events:
            objects.extend(self._build_counter_event_blocks(counter_events))

        return objects

    def _build_binary_event_blocks(self, events: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for binary events."""
        if not events:
            return []

        data = bytearray()
        max_index = max(e.index for e in events)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(events)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(events)).to_bytes_2()
            qualifier = 0x28

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            # g2v1 format: 1 byte flags
            flags = int(event.quality)
            if event.value:
                flags |= 0x80  # STATE bit
            data.append(flags)

        header = ObjectHeader(
            group=GV_BINARY_INPUT_EVENT[0],
            variation=GV_BINARY_INPUT_EVENT[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_analog_event_blocks(self, events: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for analog events."""
        if not events:
            return []

        data = bytearray()
        max_index = max(e.index for e in events)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(events)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(events)).to_bytes_2()
            qualifier = 0x28

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            # g32v1 format: 1 byte flags + 4 bytes value
            data.append(int(event.quality))
            int_value = int(event.value)
            data.extend(int_value.to_bytes(4, "little", signed=True))

        header = ObjectHeader(
            group=GV_ANALOG_INPUT_EVENT[0],
            variation=GV_ANALOG_INPUT_EVENT[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_counter_event_blocks(self, events: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for counter events."""
        if not events:
            return []

        data = bytearray()
        max_index = max(e.index for e in events)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(events)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(events)).to_bytes_2()
            qualifier = 0x28

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            # g22v1 format: 1 byte flags + 4 bytes value
            data.append(int(event.quality))
            data.extend(event.value.to_bytes(4, "little", signed=False))

        header = ObjectHeader(
            group=GV_COUNTER_EVENT[0],
            variation=GV_COUNTER_EVENT[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _read_binary_inputs(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read binary inputs for a request block."""
        points = self.database.get_all_binary_inputs()
        if not points:
            return [], IIN(0)
        return self._build_binary_input_blocks(points), IIN(0)

    def _read_binary_input_events(self) -> list[ObjectBlock]:
        """Read all binary input events."""
        return self._read_class_events(EventClass.CLASS_1)

    def _read_binary_outputs(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read binary outputs for a request block."""
        points = self.database.get_all_binary_outputs()
        if not points:
            return [], IIN(0)
        return self._build_binary_output_blocks(points), IIN(0)

    def _read_analog_inputs(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read analog inputs for a request block."""
        points = self.database.get_all_analog_inputs()
        if not points:
            return [], IIN(0)
        return self._build_analog_input_blocks(points), IIN(0)

    def _read_analog_input_events(self) -> list[ObjectBlock]:
        """Read all analog input events."""
        return self._read_class_events(EventClass.CLASS_2)

    def _read_counters(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read counters for a request block."""
        points = self.database.get_all_counters()
        if not points:
            return [], IIN(0)
        return self._build_counter_blocks(points), IIN(0)

    def _read_counter_events(self) -> list[ObjectBlock]:
        """Read all counter events."""
        return self._read_class_events(EventClass.CLASS_3)

    def _read_frozen_counters(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read frozen counters for a request block."""
        points = self.database.get_all_frozen_counters()
        if not points:
            return [], IIN(0)
        return self._build_frozen_counter_blocks(points), IIN(0)

    def _handle_write(self, request: RequestFragment) -> ResponseFragment:
        """Handle WRITE request."""
        # For now, just acknowledge the write
        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_select(self, request: RequestFragment) -> ResponseFragment:
        """Handle SELECT request."""
        results: list[tuple[int, CommandStatus]] = []
        seq = request.header.control.seq

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                # CROB - Control Relay Output Block
                block_results = self._process_crob_select(block, seq)
                results.extend(block_results)
            else:
                # Unsupported object
                pass

        # Build response with command status
        return self._build_control_response(request, results)

    def _process_crob_select(self, block: ObjectBlock, seq: int) -> list[tuple[int, CommandStatus]]:
        """Process CROB SELECT.

        Delegates parsing to _parse_crob_block which handles qualifier sizing,
        buffer validation, and control-code decoding.  FORMAT_ERROR entries are
        forwarded directly; valid entries are dispatched to the handler and, on
        success, stored as pending SELECT state.
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if crob.status == CommandStatus.FORMAT_ERROR or crob.control_code is None:
                results.append((crob.index, CommandStatus.FORMAT_ERROR))
                continue

            result = self.handler.select_binary_output(
                index=crob.index,
                code=crob.control_code,
                count=crob.op_count,
                on_time=crob.on_time,
                off_time=crob.off_time,
            )

            if result.is_success:
                select_state = SelectState(
                    index=crob.index,
                    is_binary=True,
                    control_code=crob.control_code,
                    count=crob.op_count,
                    on_time=crob.on_time,
                    off_time=crob.off_time,
                    sequence=seq,
                )
                self._state.add_select(select_state)

            results.append((crob.index, result.status))

        return results

    def _handle_operate(self, request: RequestFragment) -> ResponseFragment:
        """Handle OPERATE request."""
        results: list[tuple[int, CommandStatus]] = []
        seq = request.header.control.seq

        # Clear expired selects first
        self._state.clear_expired_selects(self.config.select_timeout)

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results = self._process_crob_operate(block, seq)
                results.extend(block_results)

        return self._build_control_response(request, results)

    def _process_crob_operate(self, block: ObjectBlock, seq: int) -> list[tuple[int, CommandStatus]]:
        """Process CROB OPERATE.

        Delegates parsing to _parse_crob_block.  FORMAT_ERROR entries are forwarded
        directly.  Valid entries are checked against stored SELECT state; mismatches
        return NO_SELECT and clear the pending state.
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if crob.status == CommandStatus.FORMAT_ERROR or crob.control_code is None:
                results.append((crob.index, CommandStatus.FORMAT_ERROR))
                continue

            select_state = self._state.get_select(crob.index)
            if select_state is None:
                results.append((crob.index, CommandStatus.NO_SELECT))
                continue

            if not select_state.matches_binary(
                crob.index, crob.control_code, crob.op_count, crob.on_time, crob.off_time
            ):
                results.append((crob.index, CommandStatus.NO_SELECT))
                self._state.remove_select(crob.index)
                continue

            result = self.handler.operate_binary_output(
                index=crob.index,
                code=crob.control_code,
                count=crob.op_count,
                on_time=crob.on_time,
                off_time=crob.off_time,
                select_sequence=select_state.sequence,
            )

            self._state.remove_select(crob.index)
            results.append((crob.index, result.status))

        return results

    def _handle_direct_operate(self, request: RequestFragment) -> ResponseFragment:
        """Handle DIRECT_OPERATE request."""
        results: list[tuple[int, CommandStatus]] = []

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results = self._process_crob_direct_operate(block)
                results.extend(block_results)

        return self._build_control_response(request, results)

    def _process_crob_direct_operate(self, block: ObjectBlock) -> list[tuple[int, CommandStatus]]:
        """Process CROB DIRECT_OPERATE.

        Delegates parsing to _parse_crob_block.  FORMAT_ERROR entries are forwarded
        directly; valid entries are dispatched immediately to the handler with no
        prior SELECT required.
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if crob.status == CommandStatus.FORMAT_ERROR or crob.control_code is None:
                results.append((crob.index, CommandStatus.FORMAT_ERROR))
                continue

            result = self.handler.direct_operate_binary_output(
                index=crob.index,
                code=crob.control_code,
                count=crob.op_count,
                on_time=crob.on_time,
                off_time=crob.off_time,
            )

            results.append((crob.index, result.status))

        return results

    def _build_control_response(
        self,
        request: RequestFragment,
        results: list[tuple[int, CommandStatus]],
    ) -> ResponseFragment:
        """Build response for control operations."""
        # Echo back the objects with status
        # For simplicity, return null response with IIN
        error_iin = IIN(0)
        for _, status in results:
            if status != CommandStatus.SUCCESS:
                # Set appropriate IIN based on error
                if status == CommandStatus.NOT_SUPPORTED:
                    error_iin |= IIN.NO_FUNC_CODE_SUPPORT
                elif status == CommandStatus.FORMAT_ERROR:
                    error_iin |= IIN.PARAMETER_ERROR

        return build_null_response(
            iin=self.iin | error_iin,
            seq=request.header.control.seq,
        )

    def _handle_cold_restart(self, request: RequestFragment) -> ResponseFragment:
        """Handle COLD_RESTART request."""
        delay = self.handler.cold_restart()
        if delay is None:
            return build_null_response(
                iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
                seq=request.header.control.seq,
            )

        # Build response with time delay object (g52v2)
        delay_data = delay.to_bytes(2, "little")
        header = ObjectHeader.build(
            group=52,
            variation=2,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.UINT8_COUNT,
        )
        count_data = CountRange(count=1).to_bytes_1()
        block = ObjectBlock(header=header, data=count_data + delay_data)

        return build_response(
            objects=(block,),
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_warm_restart(self, request: RequestFragment) -> ResponseFragment:
        """Handle WARM_RESTART request."""
        delay = self.handler.warm_restart()
        if delay is None:
            return build_null_response(
                iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
                seq=request.header.control.seq,
            )

        # Build response with time delay object (g52v2)
        delay_data = delay.to_bytes(2, "little")
        header = ObjectHeader.build(
            group=52,
            variation=2,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.UINT8_COUNT,
        )
        count_data = CountRange(count=1).to_bytes_1()
        block = ObjectBlock(header=header, data=count_data + delay_data)

        return build_response(
            objects=(block,),
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_delay_measure(self, request: RequestFragment) -> ResponseFragment:
        """Handle DELAY_MEASURE request for time sync."""
        # Respond with time delay of 0 (we process immediately)
        delay_data = (0).to_bytes(2, "little")
        header = ObjectHeader.build(
            group=52,
            variation=2,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.UINT8_COUNT,
        )
        count_data = CountRange(count=1).to_bytes_1()
        block = ObjectBlock(header=header, data=count_data + delay_data)

        # Clear NEED_TIME flag
        self._state.clear_need_time()

        return build_response(
            objects=(block,),
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_enable_unsolicited(self, request: RequestFragment) -> ResponseFragment:
        """Handle ENABLE_UNSOLICITED request."""
        for block in request.objects:
            if block.header.group == GROUP_CLASS_DATA:
                if block.header.variation == VAR_CLASS_1:
                    self._state.unsolicited.enable_class(EventClass.CLASS_1)
                elif block.header.variation == VAR_CLASS_2:
                    self._state.unsolicited.enable_class(EventClass.CLASS_2)
                elif block.header.variation == VAR_CLASS_3:
                    self._state.unsolicited.enable_class(EventClass.CLASS_3)

        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_disable_unsolicited(self, request: RequestFragment) -> ResponseFragment:
        """Handle DISABLE_UNSOLICITED request."""
        for block in request.objects:
            if block.header.group == GROUP_CLASS_DATA:
                if block.header.variation == VAR_CLASS_1:
                    self._state.unsolicited.disable_class(EventClass.CLASS_1)
                elif block.header.variation == VAR_CLASS_2:
                    self._state.unsolicited.disable_class(EventClass.CLASS_2)
                elif block.header.variation == VAR_CLASS_3:
                    self._state.unsolicited.disable_class(EventClass.CLASS_3)

        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_confirm(self, request: RequestFragment) -> ResponseFragment | None:
        """Handle CONFIRM request."""
        # Confirmations don't get a response
        seq = request.header.control.seq

        # Check if this confirms our pending unsolicited
        if self._state.unsolicited.pending_confirm and self._state.unsolicited.confirm_sequence == seq:
            self._state.unsolicited.pending_confirm = False
            self._state.unsolicited.confirm_sequence = -1

        return None

    def _handle_freeze(self, request: RequestFragment, clear: bool) -> ResponseFragment:
        """Handle FREEZE or FREEZE_CLEAR request."""
        error_iin = IIN(0)

        for block in request.objects:
            if block.header.group == GROUP_COUNTER:  # Counter group
                # Freeze all counters
                result = self.handler.freeze_counters(
                    start=0,
                    stop=65535,
                    clear=clear,
                )
                if not result.is_success:
                    error_iin |= IIN.NO_FUNC_CODE_SUPPORT

        return build_null_response(
            iin=self.iin | error_iin,
            seq=request.header.control.seq,
        )

    def generate_unsolicited(self) -> ResponseFragment | None:
        """Generate an unsolicited response if events are pending.

        Call this periodically to check for and send unsolicited responses.

        Returns:
            Unsolicited response fragment, or None if no events pending.
        """
        # Check if unsolicited is enabled
        unsolicited = self._state.unsolicited
        if not (unsolicited.class_1_enabled or unsolicited.class_2_enabled or unsolicited.class_3_enabled):
            return None

        # Check if we're waiting for a confirm
        if unsolicited.pending_confirm:
            return None

        # Check for events
        buffer = self.database.event_buffer
        objects: list[ObjectBlock] = []

        if unsolicited.class_1_enabled and buffer.class1.count > 0:
            objects.extend(self._read_class_events(EventClass.CLASS_1))
        if unsolicited.class_2_enabled and buffer.class2.count > 0:
            objects.extend(self._read_class_events(EventClass.CLASS_2))
        if unsolicited.class_3_enabled and buffer.class3.count > 0:
            objects.extend(self._read_class_events(EventClass.CLASS_3))

        if not objects:
            return None

        # Generate unsolicited response
        seq = self._state.sequences.next_unsolicited_seq()
        unsolicited.pending_confirm = True
        unsolicited.confirm_sequence = seq

        return build_unsolicited_response(
            objects=tuple(objects),
            iin=self.iin,
            seq=seq,
        )

    def clear_restart(self) -> None:
        """Clear the DEVICE_RESTART IIN flag.

        Call this after completing startup initialization.
        """
        self._state.clear_restart()
