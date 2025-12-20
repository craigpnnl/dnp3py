"""DNP3 Outstation implementation per IEEE 1815-2012.

The Outstation class handles incoming requests from a master station,
processes them according to the DNP3 protocol, and generates responses.
"""

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
        """Build object blocks for binary input points."""
        if not points:
            return []

        # Build data with indices and values
        data = bytearray()
        indices = [p.index for p in points]
        max_index = max(indices)

        # Determine index size
        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(points)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(points)).to_bytes_2()
            qualifier = 0x28

        # Build indexed data
        for point in points:
            if index_size == 1:
                data.append(point.index & 0xFF)
            else:
                data.extend(point.index.to_bytes(2, "little"))
            data.extend(_serialize_binary_input(point.value, point.quality))

        header = ObjectHeader(
            group=GV_BINARY_INPUT_FLAGS[0],
            variation=GV_BINARY_INPUT_FLAGS[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_binary_output_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for binary output points."""
        if not points:
            return []

        data = bytearray()
        indices = [p.index for p in points]
        max_index = max(indices)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(points)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(points)).to_bytes_2()
            qualifier = 0x28

        for point in points:
            if index_size == 1:
                data.append(point.index & 0xFF)
            else:
                data.extend(point.index.to_bytes(2, "little"))
            data.extend(_serialize_binary_output(point.value, point.quality))

        header = ObjectHeader(
            group=GV_BINARY_OUTPUT_FLAGS[0],
            variation=GV_BINARY_OUTPUT_FLAGS[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_analog_input_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for analog input points."""
        if not points:
            return []

        data = bytearray()
        indices = [p.index for p in points]
        max_index = max(indices)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(points)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(points)).to_bytes_2()
            qualifier = 0x28

        for point in points:
            if index_size == 1:
                data.append(point.index & 0xFF)
            else:
                data.extend(point.index.to_bytes(2, "little"))
            data.extend(_serialize_analog_input_32(point.value, int(point.quality)))

        header = ObjectHeader(
            group=GV_ANALOG_INPUT_32[0],
            variation=GV_ANALOG_INPUT_32[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for counter points."""
        if not points:
            return []

        data = bytearray()
        indices = [p.index for p in points]
        max_index = max(indices)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(points)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(points)).to_bytes_2()
            qualifier = 0x28

        for point in points:
            if index_size == 1:
                data.append(point.index & 0xFF)
            else:
                data.extend(point.index.to_bytes(2, "little"))
            data.extend(_serialize_counter_32(point.value, int(point.quality)))

        header = ObjectHeader(
            group=GV_COUNTER_32[0],
            variation=GV_COUNTER_32[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_frozen_counter_blocks(self, points: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for frozen counter points."""
        if not points:
            return []

        data = bytearray()
        indices = [p.index for p in points]
        max_index = max(indices)

        if max_index <= MAX_1_BYTE_INDEX:
            index_size = 1
            count_data = CountRange(count=len(points)).to_bytes_1()
            qualifier = 0x17
        else:
            index_size = 2
            count_data = CountRange(count=len(points)).to_bytes_2()
            qualifier = 0x28

        for point in points:
            if index_size == 1:
                data.append(point.index & 0xFF)
            else:
                data.extend(point.index.to_bytes(2, "little"))
            data.extend(_serialize_counter_32(point.value, int(point.quality)))

        header = ObjectHeader(
            group=GV_FROZEN_COUNTER_32[0],
            variation=GV_FROZEN_COUNTER_32[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

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
        """Process CROB SELECT."""
        results: list[tuple[int, CommandStatus]] = []

        # Parse CROB data - format: index (1-2 bytes) + CROB (11 bytes)
        data = block.data
        if len(data) < 1:
            return results

        # Get count from first byte
        count = data[0]
        offset = 1

        for _ in range(count):
            if offset + 12 > len(data):  # 1 byte index + 11 byte CROB
                break

            index = data[offset]
            offset += 1

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

        count = data[0]
        offset = 1

        for _ in range(count):
            if offset + 12 > len(data):
                break

            index = data[offset]
            offset += 1

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

        return self._build_control_response(request, results)

    def _process_crob_direct_operate(self, block: ObjectBlock) -> list[tuple[int, CommandStatus]]:
        """Process CROB DIRECT_OPERATE."""
        results: list[tuple[int, CommandStatus]] = []

        data = block.data
        if len(data) < 1:
            return results

        count = data[0]
        offset = 1

        for _ in range(count):
            if offset + 12 > len(data):
                break

            index = data[offset]
            offset += 1

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
