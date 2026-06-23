"""DNP3 Outstation implementation per IEEE 1815-2012.

The Outstation class handles incoming requests from a master station,
processes them according to the DNP3 protocol, and generates responses.
"""

import struct
from dataclasses import dataclass, field
from typing import Any

from dnp3.application.builder import (
    build_null_response,
    build_response,
    build_unsolicited_response,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RESPONSE_HEADER_SIZE
from dnp3.application.parser import parse_request
from dnp3.application.qualifiers import (
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
    get_prefix_size,
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
GROUP_ANALOG_OUTPUT = 41
GROUP_IIN = 80  # g80 - Internal Indications
GROUP_CLASS_DATA = 60

# Analog output variations (Group 41)
AO_VAR_INT32 = 1  # 32-bit signed integer
AO_VAR_INT16 = 2  # 16-bit signed integer
AO_VAR_FLOAT32 = 3  # Single-precision float
AO_VAR_FLOAT64 = 4  # Double-precision float

# DNP3 class data variations
VAR_CLASS_0 = 1
VAR_CLASS_1 = 2
VAR_CLASS_2 = 3
VAR_CLASS_3 = 4

# IIN bit indices (Group 80 Variation 1)
IIN_BIT_DEVICE_RESTART = 7  # Bit 7 of IIN byte 1

# Minimum data sizes
MIN_IIN_WRITE_DATA = 2  # start + stop bytes

# Index size thresholds
MAX_1_BYTE_INDEX = 255  # 0xFF
MAX_2_BYTE_INDEX = 65535  # 0xFFFF


def _parse_count_from_qualifier(data: bytes, header: ObjectHeader) -> tuple[int, int]:
    """Parse object count from data based on qualifier range code.

    Args:
        data: Raw block data starting at the count field.
        header: Object header with qualifier info.

    Returns:
        Tuple of (count, bytes_consumed_for_count).
    """
    range_code = header.range_code
    if range_code == RangeCode.UINT8_COUNT:
        if len(data) < 1:
            return 0, 0
        return data[0], 1
    if range_code == RangeCode.UINT16_COUNT:
        if len(data) < 2:
            return 0, 0
        return int.from_bytes(data[0:2], "little"), 2
    if range_code == RangeCode.UINT32_COUNT:
        if len(data) < 4:
            return 0, 0
        return int.from_bytes(data[0:4], "little"), 4
    # Fallback for unknown range codes
    if len(data) < 1:
        return 0, 0
    return data[0], 1


def _parse_index_from_qualifier(data: bytes, header: ObjectHeader) -> tuple[int, int]:
    """Parse point index from data based on qualifier prefix code.

    Args:
        data: Raw data starting at the index prefix.
        header: Object header with qualifier info.

    Returns:
        Tuple of (index, bytes_consumed_for_index).
    """
    prefix_code = header.prefix_code
    if prefix_code == PrefixCode.UINT8_INDEX:
        if len(data) < 1:
            return 0, 0
        return data[0], 1
    if prefix_code == PrefixCode.UINT16_INDEX:
        if len(data) < 2:
            return 0, 0
        return int.from_bytes(data[0:2], "little"), 2
    if prefix_code == PrefixCode.UINT32_INDEX:
        if len(data) < 4:
            return 0, 0
        return int.from_bytes(data[0:4], "little"), 4
    # No prefix — shouldn't happen for control objects but handle gracefully
    return 0, 0


def _encode_count_for_qualifier(count: int, header: ObjectHeader) -> bytes:
    """Encode object count bytes matching the qualifier range code.

    Args:
        count: Number of objects.
        header: Object header with qualifier info.

    Returns:
        Count encoded in the correct byte width.
    """
    range_code = header.range_code
    if range_code == RangeCode.UINT16_COUNT:
        return count.to_bytes(2, "little")
    if range_code == RangeCode.UINT32_COUNT:
        return count.to_bytes(4, "little")
    # Default: 1-byte count
    return bytes([count & 0xFF])


def _encode_index_for_qualifier(index: int, header: ObjectHeader) -> bytes:
    """Encode point index bytes matching the qualifier prefix code.

    Args:
        index: Point index.
        header: Object header with qualifier info.

    Returns:
        Index encoded in the correct byte width.
    """
    prefix_code = header.prefix_code
    if prefix_code == PrefixCode.UINT16_INDEX:
        return index.to_bytes(2, "little")
    if prefix_code == PrefixCode.UINT32_INDEX:
        return index.to_bytes(4, "little")
    # Default: 1-byte index
    return bytes([index & 0xFF])


def _index_size_from_qualifier(header: ObjectHeader) -> int:
    """Get index prefix size in bytes from qualifier."""
    return get_prefix_size(header.prefix_code)


def _split_response_objects(
    objects: list[ObjectBlock],
    iin: IIN,
    seq: int,
    max_fragment_size: int,
) -> list[ResponseFragment]:
    """Split object blocks into multiple response fragments.

    Each fragment respects max_fragment_size. FIR/FIN flags are set:
    - Single fragment: FIR=True, FIN=True
    - First of multiple: FIR=True, FIN=False
    - Middle: FIR=False, FIN=False
    - Last: FIR=False, FIN=True

    Args:
        objects: Object blocks to distribute across fragments.
        iin: Internal indications for all fragments.
        seq: Sequence number for all fragments.
        max_fragment_size: Maximum bytes per fragment.

    Returns:
        List of response fragments, each within size limit.
    """
    if not objects:
        return [build_response(objects=(), iin=iin, seq=seq, fir=True, fin=True)]

    fragments: list[ResponseFragment] = []
    current_objects: list[ObjectBlock] = []
    current_size = RESPONSE_HEADER_SIZE

    for obj in objects:
        obj_size = obj.size

        if current_size + obj_size > max_fragment_size and current_objects:
            # Current batch is full, emit a fragment
            is_first = len(fragments) == 0
            fragments.append(
                build_response(
                    objects=tuple(current_objects),
                    iin=iin,
                    seq=seq,
                    fir=is_first,
                    fin=False,
                )
            )
            current_objects = []
            current_size = RESPONSE_HEADER_SIZE

        current_objects.append(obj)
        current_size += obj_size

    # Emit final fragment
    if current_objects:
        is_first = len(fragments) == 0
        fragments.append(
            build_response(
                objects=tuple(current_objects),
                iin=iin,
                seq=seq,
                fir=is_first,
                fin=True,
            )
        )

    return fragments


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


def _calculate_chunk_size(
    max_fragment_size: int,
    per_point_size: int,
    index_size: int,
) -> int:
    """Calculate how many points fit in one ObjectBlock within a fragment.

    Accounts for response header, object header, and count prefix.

    Args:
        max_fragment_size: Maximum fragment size in bytes.
        per_point_size: Bytes per serialized point (excluding index).
        index_size: Bytes per index (1 or 2).

    Returns:
        Maximum number of points per ObjectBlock.
    """
    from dnp3.application.qualifiers import OBJECT_HEADER_SIZE

    # Available space = max_fragment - response_header - object_header - count_prefix
    # count_prefix is 1 byte for <=255 points, 2 bytes for >255
    # Use 2-byte count to be safe
    count_prefix_size = 2 if index_size == 2 else 1
    overhead = RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + count_prefix_size
    available = max_fragment_size - overhead
    bytes_per_point = index_size + per_point_size
    if bytes_per_point <= 0:
        return 1
    return max(1, available // bytes_per_point)


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

    def process_request(self, data: bytes) -> list[ResponseFragment]:
        """Process a request and generate response fragment(s).

        Args:
            data: Raw request bytes (application layer fragment).

        Returns:
            List of response fragments. Empty list if no response needed.
            For READ requests with large databases, may return multiple
            fragments respecting max_fragment_size.
        """
        try:
            request = parse_request(data)
        except Exception:
            # Parse error - return null response with PARAMETER_ERROR
            return [build_null_response(iin=self.iin | IIN.PARAMETER_ERROR)]

        return self._process_request_fragment(request)

    def _process_request_fragment(self, request: RequestFragment) -> list[ResponseFragment]:
        """Process a parsed request fragment.

        Args:
            request: Parsed request fragment.

        Returns:
            List of response fragments. Empty list if no response needed.
        """
        header = request.header
        function = header.function

        # Track request sequence
        self._state.sequences.last_request_seq = header.control.seq

        # Dispatch based on function code
        if function == FunctionCode.READ:
            return self._handle_read(request)
        if function == FunctionCode.WRITE:
            return [self._handle_write(request)]
        if function == FunctionCode.SELECT:
            return [self._handle_select(request)]
        if function == FunctionCode.OPERATE:
            return [self._handle_operate(request)]
        if function == FunctionCode.DIRECT_OPERATE:
            return [self._handle_direct_operate(request)]
        if function == FunctionCode.DIRECT_OPERATE_NO_ACK:
            self._handle_direct_operate(request)
            return []  # No response for NO_ACK
        if function == FunctionCode.COLD_RESTART:
            return [self._handle_cold_restart(request)]
        if function == FunctionCode.WARM_RESTART:
            return [self._handle_warm_restart(request)]
        if function == FunctionCode.DELAY_MEASURE:
            return [self._handle_delay_measure(request)]
        if function == FunctionCode.ENABLE_UNSOLICITED:
            return [self._handle_enable_unsolicited(request)]
        if function == FunctionCode.DISABLE_UNSOLICITED:
            return [self._handle_disable_unsolicited(request)]
        if function == FunctionCode.CONFIRM:
            result = self._handle_confirm(request)
            return [result] if result is not None else []
        if function == FunctionCode.IMMEDIATE_FREEZE:
            return [self._handle_freeze(request, clear=False)]
        if function == FunctionCode.FREEZE_CLEAR:
            return [self._handle_freeze(request, clear=True)]

        # Unsupported function code
        return [
            build_null_response(
                iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
                seq=header.control.seq,
            )
        ]

    def _handle_read(self, request: RequestFragment) -> list[ResponseFragment]:
        """Handle READ request, splitting into multiple fragments if needed."""
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

        return _split_response_objects(
            objects=objects,
            iin=self.iin | error_iin,
            seq=request.header.control.seq,
            max_fragment_size=self.config.max_fragment_size,
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
        """Build object blocks for binary input points, chunked for fragment size."""
        return self._build_indexed_point_blocks(
            points=points,
            group=GV_BINARY_INPUT_FLAGS[0],
            variation=GV_BINARY_INPUT_FLAGS[1],
            serializer=lambda p: _serialize_binary_input(p.value, p.quality),
            per_point_data_size=1,  # g1v2: 1 byte flags
        )

    def _build_binary_output_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for binary output points, chunked for fragment size."""
        return self._build_indexed_point_blocks(
            points=points,
            group=GV_BINARY_OUTPUT_FLAGS[0],
            variation=GV_BINARY_OUTPUT_FLAGS[1],
            serializer=lambda p: _serialize_binary_output(p.value, p.quality),
            per_point_data_size=1,  # g10v2: 1 byte flags
        )

    def _build_analog_input_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for analog input points, chunked for fragment size."""
        return self._build_indexed_point_blocks(
            points=points,
            group=GV_ANALOG_INPUT_32[0],
            variation=GV_ANALOG_INPUT_32[1],
            serializer=lambda p: _serialize_analog_input_32(p.value, int(p.quality)),
            per_point_data_size=5,  # g30v1: 1 byte flags + 4 byte value
        )

    def _build_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for counter points, chunked for fragment size."""
        return self._build_indexed_point_blocks(
            points=points,
            group=GV_COUNTER_32[0],
            variation=GV_COUNTER_32[1],
            serializer=lambda p: _serialize_counter_32(p.value, int(p.quality)),
            per_point_data_size=5,  # g20v1: 1 byte flags + 4 byte value
        )

    def _build_frozen_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for frozen counter points, chunked for fragment size."""
        return self._build_indexed_point_blocks(
            points=points,
            group=GV_FROZEN_COUNTER_32[0],
            variation=GV_FROZEN_COUNTER_32[1],
            serializer=lambda p: _serialize_counter_32(p.value, int(p.quality)),
            per_point_data_size=5,  # g21v1: 1 byte flags + 4 byte value
        )

    def _build_indexed_point_blocks(
        self,
        points: list[Any],
        group: int,
        variation: int,
        serializer: Any,
        per_point_data_size: int,
    ) -> list[ObjectBlock]:
        """Build chunked object blocks for indexed points.

        Splits points into multiple ObjectBlocks so each block fits
        within a single fragment respecting max_fragment_size.

        Args:
            points: List of point objects with .index attribute.
            group: DNP3 group number.
            variation: DNP3 variation number.
            serializer: Callable that takes a point and returns bytes.
            per_point_data_size: Bytes per point (excluding index bytes).

        Returns:
            List of ObjectBlocks, each small enough for a fragment.
        """
        if not points:
            return []

        max_index = max(p.index for p in points)
        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            qualifier = 0x17
        else:
            index_size = 2
            qualifier = 0x28

        chunk_size = _calculate_chunk_size(
            self.config.max_fragment_size,
            per_point_data_size,
            index_size,
        )

        blocks: list[ObjectBlock] = []
        for start in range(0, len(points), chunk_size):
            chunk = points[start : start + chunk_size]

            if index_size == 1:
                count_data = CountRange(count=len(chunk)).to_bytes_1()
            else:
                count_data = CountRange(count=len(chunk)).to_bytes_2()

            data = bytearray()
            for point in chunk:
                if index_size == 1:
                    data.append(point.index & 0xFF)
                else:
                    data.extend(point.index.to_bytes(2, "little"))
                data.extend(serializer(point))

            header = ObjectHeader(
                group=group,
                variation=variation,
                qualifier=qualifier,
            )
            blocks.append(ObjectBlock(header=header, data=count_data + bytes(data)))

        return blocks

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
        """Handle WRITE request.

        Supports Group 80 Variation 1 (Internal Indications) to allow
        the master to clear IIN bits such as DEVICE_RESTART.
        """
        for block in request.objects:
            if block.header.group == GROUP_IIN and block.header.variation == 1:
                self._handle_write_iin(block)

        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_write_iin(self, block: ObjectBlock) -> None:
        """Handle WRITE for Group 80 Variation 1 (Internal Indications).

        Per IEEE 1815-2012, writing g80v1 with index 7 value 0 clears
        the DEVICE_RESTART bit. Uses start-stop range qualifier (0x00).

        Args:
            block: Object block with g80v1 data.
        """
        data = block.data
        if len(data) < MIN_IIN_WRITE_DATA:
            return

        # Qualifier 0x00 = 1-byte start-stop range
        start = data[0]
        stop = data[1]

        # The bit data follows the range bytes
        # For g80v1, each bit in the data corresponds to an IIN bit
        bit_offset = MIN_IIN_WRITE_DATA
        for bit_index in range(start, stop + 1):
            byte_pos = bit_offset + (bit_index - start) // 8
            bit_pos = (bit_index - start) % 8
            if byte_pos >= len(data):
                break

            bit_value = (data[byte_pos] >> bit_pos) & 1

            if bit_index == IIN_BIT_DEVICE_RESTART and bit_value == 0:
                self._state.clear_restart()

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
        """Process CROB SELECT."""
        results: list[tuple[int, CommandStatus]] = []

        data = block.data
        if len(data) < 1:
            return results

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        for _ in range(count):
            if offset + index_size + 11 > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            offset += idx_consumed

            # Parse CROB: control code (1) + count (1) + on_time (4) + off_time (4) + status (1)
            control_code = ControlCode(data[offset] & 0x0F)
            op_count = data[offset + 1]
            on_time = int.from_bytes(data[offset + 2 : offset + 6], "little")
            off_time = int.from_bytes(data[offset + 6 : offset + 10], "little")
            offset += 11

            # Call handler
            result = self.handler.select_binary_output(
                index=index,
                code=control_code,
                count=op_count,
                on_time=on_time,
                off_time=off_time,
            )

            if result.is_success:
                # Store SELECT state
                select_state = SelectState(
                    index=index,
                    is_binary=True,
                    control_code=control_code,
                    count=op_count,
                    on_time=on_time,
                    off_time=off_time,
                    sequence=seq,
                )
                self._state.add_select(select_state)

            results.append((index, result.status))

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
        """Process CROB OPERATE."""
        results: list[tuple[int, CommandStatus]] = []

        data = block.data
        if len(data) < 1:
            return results

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        for _ in range(count):
            if offset + index_size + 11 > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            offset += idx_consumed

            control_code = ControlCode(data[offset] & 0x0F)
            op_count = data[offset + 1]
            on_time = int.from_bytes(data[offset + 2 : offset + 6], "little")
            off_time = int.from_bytes(data[offset + 6 : offset + 10], "little")
            offset += 11

            # Check for matching SELECT
            select_state = self._state.get_select(index)
            if select_state is None:
                results.append((index, CommandStatus.NO_SELECT))
                continue

            if not select_state.matches_binary(index, control_code, op_count, on_time, off_time):
                results.append((index, CommandStatus.NO_SELECT))
                self._state.remove_select(index)
                continue

            # Call handler
            result = self.handler.operate_binary_output(
                index=index,
                code=control_code,
                count=op_count,
                on_time=on_time,
                off_time=off_time,
                select_sequence=select_state.sequence,
            )

            # Clear SELECT state after OPERATE
            self._state.remove_select(index)

            results.append((index, result.status))

        return results

    def _handle_direct_operate(self, request: RequestFragment) -> ResponseFragment:
        """Handle DIRECT_OPERATE request."""
        results: list[tuple[int, CommandStatus]] = []

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results = self._process_crob_direct_operate(block)
                results.extend(block_results)
            elif block.header.group == GROUP_ANALOG_OUTPUT:
                block_results = self._process_ao_direct_operate(block)
                results.extend(block_results)

        return self._build_control_response(request, results)

    def _process_crob_direct_operate(self, block: ObjectBlock) -> list[tuple[int, CommandStatus]]:
        """Process CROB DIRECT_OPERATE."""
        results: list[tuple[int, CommandStatus]] = []

        data = block.data
        if len(data) < 1:
            return results

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        for _ in range(count):
            if offset + index_size + 11 > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            offset += idx_consumed

            control_code = ControlCode(data[offset] & 0x0F)
            op_count = data[offset + 1]
            on_time = int.from_bytes(data[offset + 2 : offset + 6], "little")
            off_time = int.from_bytes(data[offset + 6 : offset + 10], "little")
            offset += 11

            result = self.handler.direct_operate_binary_output(
                index=index,
                code=control_code,
                count=op_count,
                on_time=on_time,
                off_time=off_time,
            )

            results.append((index, result.status))

        return results

    def _process_ao_direct_operate(self, block: ObjectBlock) -> list[tuple[int, CommandStatus]]:
        """Process Analog Output DIRECT_OPERATE (Group 41).

        Supports variations 1-4:
            Var 1: 32-bit signed integer (4 bytes value + 1 byte status)
            Var 2: 16-bit signed integer (2 bytes value + 1 byte status)
            Var 3: single-precision float (4 bytes value + 1 byte status)
            Var 4: double-precision float (8 bytes value + 1 byte status)
        """
        results: list[tuple[int, CommandStatus]] = []
        variation = block.header.variation

        # Determine value size from variation
        value_sizes = {AO_VAR_INT32: 4, AO_VAR_INT16: 2, AO_VAR_FLOAT32: 4, AO_VAR_FLOAT64: 8}
        value_size = value_sizes.get(variation)
        if value_size is None:
            return results

        data = block.data
        if len(data) < 1:
            return results

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        # object size = index_size + value_size + 1 byte status
        obj_size = index_size + value_size + 1

        for _ in range(count):
            if offset + obj_size > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            offset += idx_consumed

            # Parse value based on variation
            raw_value = data[offset : offset + value_size]
            if variation in {AO_VAR_INT32, AO_VAR_INT16}:
                value = float(int.from_bytes(raw_value, "little", signed=True))
            elif variation == AO_VAR_FLOAT32:
                value = float(struct.unpack("<f", raw_value)[0])
            elif variation == AO_VAR_FLOAT64:
                value = float(struct.unpack("<d", raw_value)[0])
            else:
                value = 0.0

            offset += value_size
            offset += 1  # skip request status byte

            result = self.handler.direct_operate_analog_output(
                index=index,
                value=value,
            )

            results.append((index, result.status))

        return results

    def _build_control_response(
        self,
        request: RequestFragment,
        results: list[tuple[int, CommandStatus]],
    ) -> ResponseFragment:
        """Build response for control operations.

        Per IEEE 1815-2012, the response must echo back the same object
        headers with each command object's status field set to the result.
        """
        # Build a lookup from index to status
        status_map: dict[int, CommandStatus] = {}
        for index, status in results:
            status_map[index] = status

        objects: list[ObjectBlock] = []

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                echoed = self._echo_crob_block(block, status_map)
                objects.append(echoed)
            elif block.header.group == GROUP_ANALOG_OUTPUT:
                echoed = self._echo_ao_block(block, status_map)
                objects.append(echoed)
            else:
                # For unsupported object types, echo the block as-is
                objects.append(block)

        return build_response(
            objects=tuple(objects),
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _echo_crob_block(
        self,
        block: ObjectBlock,
        status_map: dict[int, CommandStatus],
    ) -> ObjectBlock:
        """Echo a CROB block with status bytes set from results.

        Args:
            block: Original request CROB block.
            status_map: Map of point index to command status.

        Returns:
            ObjectBlock with status bytes updated.
        """
        data = block.data
        if len(data) < 1:
            return block

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        result_data = bytearray(_encode_count_for_qualifier(count, block.header))

        for _ in range(count):
            if offset + index_size + 11 > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            # Write index in the same byte width as the request
            result_data.extend(_encode_index_for_qualifier(index, block.header))
            offset += idx_consumed

            # Copy CROB fields (10 bytes: control + count + on_time + off_time)
            result_data.extend(data[offset : offset + 10])
            offset += 10

            # Skip the original status byte
            offset += 1

            # Write the result status byte
            status = status_map.get(index, CommandStatus.NOT_SUPPORTED)
            result_data.append(int(status))

        return ObjectBlock(header=block.header, data=bytes(result_data))

    def _echo_ao_block(
        self,
        block: ObjectBlock,
        status_map: dict[int, CommandStatus],
    ) -> ObjectBlock:
        """Echo an Analog Output block with status bytes set from results.

        Args:
            block: Original request AO block.
            status_map: Map of point index to command status.

        Returns:
            ObjectBlock with status bytes updated.
        """
        variation = block.header.variation
        value_sizes = {AO_VAR_INT32: 4, AO_VAR_INT16: 2, AO_VAR_FLOAT32: 4, AO_VAR_FLOAT64: 8}
        value_size = value_sizes.get(variation, 4)

        data = block.data
        if len(data) < 1:
            return block

        count, count_size = _parse_count_from_qualifier(data, block.header)
        offset = count_size
        index_size = _index_size_from_qualifier(block.header)

        result_data = bytearray(_encode_count_for_qualifier(count, block.header))

        for _ in range(count):
            obj_size = index_size + value_size + 1  # index + value + status
            if offset + obj_size > len(data):
                break

            index, idx_consumed = _parse_index_from_qualifier(data[offset:], block.header)
            # Write index in the same byte width as the request
            result_data.extend(_encode_index_for_qualifier(index, block.header))
            offset += idx_consumed

            # Copy value bytes
            result_data.extend(data[offset : offset + value_size])
            offset += value_size

            # Skip original status byte
            offset += 1

            # Write the result status byte
            status = status_map.get(index, CommandStatus.NOT_SUPPORTED)
            result_data.append(int(status))

        return ObjectBlock(header=block.header, data=bytes(result_data))

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
