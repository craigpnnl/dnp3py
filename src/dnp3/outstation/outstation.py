"""DNP3 Outstation implementation per IEEE 1815-2012.

The Outstation class handles incoming requests from a master station,
processes them according to the DNP3 protocol, and generates responses.
"""

import logging
import math
import struct
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from dnp3.application.builder import (
    build_null_response,
    build_response,
    build_unsolicited_response,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment, Truncation, TruncationReason
from dnp3.application.header import MAX_APP_SEQUENCE, RESPONSE_HEADER_SIZE
from dnp3.application.parser import parse_request
from dnp3.application.qualifiers import (
    OBJECT_HEADER_SIZE,
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
)
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.core.timestamp import TIMESTAMP_SIZE, DNP3Timestamp
from dnp3.database import AnalogEvent, BinaryEvent, CounterEvent, Database, EventClass
from dnp3.objects.analog_input import AnalogInput32, AnalogInputEvent32
from dnp3.objects.binary_input import BinaryInputEvent, BinaryInputFlags
from dnp3.objects.binary_output import BinaryOutputFlags
from dnp3.objects.binary_output import CommandStatus as ObjectsCommandStatus
from dnp3.objects.counter import Counter32, CounterEvent32Time, FrozenCounter32
from dnp3.outstation._failure_log import WINDOW_SECONDS, FailureKey, FailureLogLimiter
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandHandler, CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId
from dnp3.outstation.state import (
    OutstationState,
    OutstationStateManager,
    SelectState,
)

# #119 tracks adding logging throughout this module; today it warns when a
# commanded NaN analog output value cannot be stored, and logs the traceback
# of a handler exception caught in process_request (#46).
_log = logging.getLogger(__name__)

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
# g22v5: 32-bit counter event WITH 48-bit timestamp, required for MESA/DER
# settlement-grade energy accounting (Vance domain guidance).
GV_COUNTER_EVENT = (22, 5)  # g22v5 - 32-bit Counter Event with time

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
GROUP_ANALOG_OUTPUT_STATUS = 40
GROUP_ANALOG_OUTPUT = 41
GROUP_TIME_AND_DATE = 50  # g50 - Time and Date
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
IIN_BIT_NEED_TIME = 4  # Bit 4 of IIN byte 1 (IEEE 1815-2012 4.5.5)

# Minimum data sizes
MIN_IIN_WRITE_DATA = 2  # start + stop bytes

# Identifies one buffered event for dedup and removal across a response
# (#46). A bare serial is not enough: ClassBuffer.add falls back to its own
# per-class counter when called with no explicit serial (event_buffer.py),
# so two events in different classes can carry the same serial number.
_EventKey = tuple[EventClass, int]

# A.23.1.2.3 fixes the WRITE qualifier for g50v1 to 0x07 (1-byte count) and
# the count to 1; any other qualifier or count is not the time-set object.
_WRITE_TIME_QUALIFIER = 0x07

# A.23.3 fixes g50v3 (the LAN-synchronized time write, #142) to this variation.
_VARIATION_TIME_LAN_WRITE = 3

# DNP3Timestamp is unsigned and TIMESTAMP_SIZE (6) octets wide: the largest
# value a g50v3 delivery can carry without overflowing DNP3Timestamp.to_bytes.
_MAX_TIMESTAMP_MS = (1 << (TIMESTAMP_SIZE * 8)) - 1

# Analog output value sizes in bytes, keyed by variation number
# (parallel to _CROB_BODY_BYTES for CROB).
_AO_VALUE_SIZES: dict[int, int] = {
    AO_VAR_INT32: 4,  # Group 41 Var 1: 32-bit signed integer
    AO_VAR_INT16: 2,  # Group 41 Var 2: 16-bit signed integer
    AO_VAR_FLOAT32: 4,  # Group 41 Var 3: single-precision float
    AO_VAR_FLOAT64: 8,  # Group 41 Var 4: double-precision float
}

# Group 40 (Analog Output Status) per-point wire size: the g41 value size plus
# the leading flag octet every g40 variation carries (IEEE 1815-2012 A.19).
_AO_STATUS_SIZES: dict[int, int] = {variation: size + 1 for variation, size in _AO_VALUE_SIZES.items()}

# Signed integer range of each g40 int variation, for the 11.6.1.1
# clamp: a value outside this range is reported as the nearer bound.
_AO_STATUS_INT_LIMITS: dict[int, tuple[int, int]] = {
    AO_VAR_INT32: (-(2**31), 2**31 - 1),
    AO_VAR_INT16: (-(2**15), 2**15 - 1),
}

# Largest finite IEEE 754 binary32 magnitude (bit pattern 0x7F7FFFFF), the g40v3
# clamp limit: struct.pack("<f", ...) raises OverflowError above this for any
# finite value, so it is the bound 11.6.1.1 clamps to.
_FLOAT32_MAX = struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]

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

# Octets of each control object after its index prefix, keyed by (group, variation); the
# status octet is the last. The control gate and the echo share it so they frame alike.
_CONTROL_OBJECT_BYTES: dict[tuple[int, int], int] = {
    (GROUP_CROB, 1): _CROB_BODY_BYTES,
    **{(GROUP_ANALOG_OUTPUT, variation): size + 1 for variation, size in _AO_VALUE_SIZES.items()},
}

# IEEE 1815-2012 4.4.5 to 4.4.8: an outstation shall not respond to these functions.
_NO_ACK_FUNCTIONS = frozenset(
    {
        FunctionCode.DIRECT_OPERATE_NO_ACK,
        FunctionCode.IMMEDIATE_FREEZE_NO_ACK,
        FunctionCode.FREEZE_CLEAR_NO_ACK,
        FunctionCode.FREEZE_AT_TIME_NO_ACK,
    }
)

# Runs a request's objects and returns what is sent back.
_Executor = Callable[[RequestFragment], list[ResponseFragment]]


def _answered(handle: Callable[[RequestFragment], ResponseFragment]) -> _Executor:
    return lambda request: [handle(request)]


def _unanswered(handle: Callable[[RequestFragment], object]) -> _Executor:
    def execute(request: RequestFragment) -> list[ResponseFragment]:
        handle(request)
        return []

    return execute


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
        seq: Sequence number of the request; the first fragment carries this
            value and each subsequent fragment increments it, modulo 16, per
            IEEE 1815-2012 4.2.2.4.5.
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
                    seq=(seq + len(fragments)) % (MAX_APP_SEQUENCE + 1),
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
                seq=(seq + len(fragments)) % (MAX_APP_SEQUENCE + 1),
                fir=is_first,
                fin=True,
            )
        )

    return fragments


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


# Widest start/stop range data: 4-byte start + 4-byte stop. Reserved when
# sizing a chunk so a block stays within a fragment even at a 4-byte index.
_MAX_RANGE_DATA_SIZE = 8


def _static_block_capacity(max_fragment_size: int, per_point_size: int) -> int:
    """Maximum points that fit in one start/stop ObjectBlock within a fragment.

    Start/stop range encoding carries no per-object index prefix, so a block
    holds the response header, one object header, the start/stop range data, and
    the serialized point values. The widest range-data width is reserved so the
    chunk is wire-safe even for a 4-byte index. The result is at least 1 so a
    single oversized point still produces a block rather than an empty result.

    Args:
        max_fragment_size: Maximum bytes per response fragment.
        per_point_size: Serialized bytes for one point value (no index prefix).

    Returns:
        Point count per block, at least 1.
    """
    overhead = RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + _MAX_RANGE_DATA_SIZE
    available = max_fragment_size - overhead
    if per_point_size <= 0 or available < per_point_size:
        return 1
    return available // per_point_size


def _event_block_capacity(max_fragment_size: int, per_event_size: int) -> int:
    """Maximum events per block for 0x17-qualified (count+index) event encoding.

    Overhead: RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + 1-byte count field.
    Result is capped at 255 so the 1-byte count field (0x17 qualifier) always
    suffices for the computed chunk size.

    Args:
        max_fragment_size: Maximum bytes per response fragment.
        per_event_size: Serialized bytes per event (index prefix + payload).

    Returns:
        Event count per block, at least 1.
    """
    # 1-byte count field for 0x17 qualifier
    overhead = RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + 1
    available = max_fragment_size - overhead
    if per_event_size <= 0 or available < per_event_size:
        return 1
    return min(available // per_event_size, 255)


def _chunk_run(run: list[Any], max_points_per_block: int | None) -> list[list[Any]]:
    """Split one contiguous run into sub-runs of at most max_points_per_block.

    A None or non-positive limit returns the run unchanged (one block per run),
    preserving the unchunked Issue #6 behaviour. Each sub-run is a gap-free slice
    of the original run, so it remains start/stop encodable; chunking only
    partitions a run, it never changes the wire qualifier of a block.
    """
    if max_points_per_block is None or max_points_per_block <= 0:
        return [run]
    return [run[i : i + max_points_per_block] for i in range(0, len(run), max_points_per_block)]


def _build_static_blocks(
    group: int,
    variation: int,
    points: list[Any],
    serialize: Callable[[Any], bytes],
    max_points_per_block: int | None = None,
) -> list[ObjectBlock]:
    """Build ObjectBlocks for static data using start/stop range qualifiers.

    Splits the point list into contiguous index runs first.  Each run becomes
    one ObjectBlock with the correct start/stop range header and no per-object
    index prefix, conforming to IEEE 1815-2012 Table 4-2.

    When max_points_per_block is set, each contiguous run is further partitioned
    into sub-runs of at most that many points so every emitted block fits inside
    one response fragment (the multi-fragment send path packs whole blocks). Each
    sub-run stays contiguous, so the start/stop qualifier (0x00/0x01) is identical
    to the unchunked case; only the run is partitioned, never the wire encoding.

    Args:
        group: Object group number.
        variation: Object variation number.
        points: Sorted list of points (may be sparse).
        serialize: Callable that converts a single point to its wire bytes.
        max_points_per_block: Optional cap on points per block for fragment
            sizing. None emits one block per contiguous run (Issue #6 default).

    Returns:
        One ObjectBlock per contiguous (sub-)run, in index order.
    """
    blocks: list[ObjectBlock] = []
    for run in _contiguous_runs(points):
        for chunk in _chunk_run(run, max_points_per_block):
            header, range_data = _build_start_stop_header(
                group=group,
                variation=variation,
                start=chunk[0].index,
                stop=chunk[-1].index,
            )
            data = bytearray()
            for point in chunk:
                data.extend(serialize(point))
            blocks.append(ObjectBlock(header=header, data=range_data + bytes(data)))
    return blocks


def _clamp_int_range(value: float, min_value: int, max_value: int) -> tuple[int, bool]:
    """Clamp a value into [min_value, max_value] per IEEE 1815-2012 11.6.1.1 rules 2 and 3.

    The range check runs before int(), because a stored value may be
    infinite and int(inf) raises OverflowError. NaN fails both
    comparisons and falls to int(value), which raises ValueError; a live
    caller never triggers that path today, since AnalogInputPoint and
    AnalogOutputPoint both refuse NaN before it reaches their stored
    value or any event derived from it (#159, #171).

    Args:
        value: The measured value, finite, infinite, or NaN.
        min_value: The variation's lower bound, inclusive.
        max_value: The variation's upper bound, inclusive.

    Returns:
        (value_to_encode, over_range): over_range is True when value fell
        outside the bound and value_to_encode is the nearer limit.
    """
    if value > max_value or value < min_value:
        return (max_value if value > 0 else min_value), True
    return int(value), False


def _serialize_analog_output_status(point: Any, variation: int) -> bytes:
    """Serialize one analog output status point to its g40 variation's wire bytes.

    IEEE 1815-2012 11.6.1.1 rules 2 and 3: a value outside the
    variation's range is reported as the variation's limit value with
    OVER_RANGE set in the flag octet, rather than raised or wrapped.

    Args:
        point: An AnalogOutputPoint with `quality` and `value`.
        variation: 1 (32-bit int), 2 (16-bit int), 3 (float32), or 4 (float64).

    Returns:
        The flag octet followed by the variation's little-endian value field.
    """
    quality = point.quality
    value = point.value

    if variation in _AO_STATUS_INT_LIMITS:
        min_value, max_value = _AO_STATUS_INT_LIMITS[variation]
        clamped, over_range = _clamp_int_range(value, min_value, max_value)
        if over_range:
            quality = quality | AnalogQuality.OVER_RANGE
        return bytes([int(quality)]) + clamped.to_bytes(_AO_VALUE_SIZES[variation], "little", signed=True)

    if variation == AO_VAR_FLOAT32:
        # Infinity packs into binary32 without error, so only a finite value
        # too large for binary32 (e.g. 1e40) triggers the clamp.
        if math.isfinite(value) and abs(value) > _FLOAT32_MAX:
            quality = quality | AnalogQuality.OVER_RANGE
            value = _FLOAT32_MAX if value > 0 else -_FLOAT32_MAX
        return bytes([int(quality)]) + struct.pack("<f", value)

    # AO_VAR_FLOAT64: every double this point can hold, infinity included,
    # packs into binary64 without overflow.
    return bytes([int(quality)]) + struct.pack("<d", value)


def _serialize_analog_input(point: Any) -> bytes:
    """Serialize one g30v1 analog input point to its wire bytes (#159).

    IEEE 1815-2012 11.6.1.1 rules 2 and 3: a value outside the 32-bit
    range, infinity included, is reported as that limit with OVER_RANGE
    set, rather than raised.

    Args:
        point: An AnalogInputPoint with `quality` and `value`.

    Returns:
        The 5-byte g30v1 wire encoding (flag octet then signed 32-bit value).
    """
    quality = point.quality
    clamped, over_range = _clamp_int_range(point.value, AnalogInput32.MIN_VALUE, AnalogInput32.MAX_VALUE)
    if over_range:
        quality = quality | AnalogQuality.OVER_RANGE
    return AnalogInput32(quality=quality, value=clamped).to_bytes()


def _serialize_analog_input_event(event: Any) -> bytes:
    """Serialize one g32v1 analog input event to its wire bytes (#159).

    Same 11.6.1.1 rules 2/3 clamp as _serialize_analog_input; events share
    the g30v1 range since both are 32-bit signed fields.

    Args:
        event: An AnalogEvent with `quality` and `value`.

    Returns:
        The 5-byte g32v1 wire encoding (flag octet then signed 32-bit value).
    """
    quality = event.quality
    clamped, over_range = _clamp_int_range(event.value, AnalogInputEvent32.MIN_VALUE, AnalogInputEvent32.MAX_VALUE)
    if over_range:
        quality = quality | AnalogQuality.OVER_RANGE
    return AnalogInputEvent32(quality=quality, value=clamped).to_bytes()


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


@dataclass(frozen=True)
class ParsedCrob:
    """One parsed CROB object from a received request block.

    When ``control_code`` is None, ``status`` is FORMAT_ERROR (undefined
    Op Type, truncated buffer, or unknown qualifier) or NOT_SUPPORTED (Queue
    bit set).  ``control_code`` is None exactly when ``status`` is not SUCCESS,
    so callers branch on ``control_code`` and report ``status`` when it is None.

    Attributes:
        index: Point index addressed by this CROB.
        control_code: Decoded control-code octet, or None for a rejected entry.
        op_count: Operation count field.
        on_time: On-time in milliseconds.
        off_time: Off-time in milliseconds.
        status: FORMAT_ERROR, NOT_SUPPORTED, or a SUCCESS sentinel (callers apply real status).
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
      - Undefined Op Type (5-15) in the control-code octet
    A control code with the obsolete Queue bit set is NOT_SUPPORTED
    (IEEE 1815-2012 A.8.1.2.2).

    Frame-level vs per-object failure semantics:

    Frame-level failures (unknown qualifier, count-field truncated before any
    object is reached) return a single-element list containing a synthetic
    ParsedCrob with index=0 and status=FORMAT_ERROR. The index=0 is a
    placeholder: no real point index is available at that parse stage. The
    single-element return is intentional: an empty list would leave callers
    with no result to forward to _build_control_response, so IIN.PARAMETER_ERROR
    would never be set and the malformed frame would produce a clean null
    response (silent protocol violation).

    Per-object failures carry the real parsed index and status=FORMAT_ERROR
    (undefined Op Type, truncated body discovered mid-loop) or NOT_SUPPORTED
    (Queue bit set), so the caller can include the correct point index in the response.

    In all cases control_code=None signals the entry is a rejection sentinel,
    and control_code is set only when status is SUCCESS.

    Args:
        block: CROB ObjectBlock from a SELECT, OPERATE, or DIRECT_OPERATE request.

    Returns:
        List of ParsedCrob entries. Empty only when the payload itself is empty
        (zero-length data field). Otherwise contains at least one entry, which
        may be a FORMAT_ERROR sentinel on frame-level parse failure.
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
            control_code = ControlCode(data[offset])
        except ValueError:
            rejection: CommandStatus | None = CommandStatus.FORMAT_ERROR
        else:
            rejection = CommandStatus.NOT_SUPPORTED if control_code.queue else None
        if rejection is not None:
            parsed.append(
                ParsedCrob(
                    index=index,
                    control_code=None,
                    op_count=0,
                    on_time=0,
                    off_time=0,
                    status=rejection,
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


def _parse_ao_block(block: ObjectBlock) -> list[tuple[int, float]]:
    """Parse an Analog Output block (Group 41) into (index, value) pairs, in wire order.

    Supports variations 1-4:
        Var 1: 32-bit signed integer (4 bytes value + 1 byte status)
        Var 2: 16-bit signed integer (2 bytes value + 1 byte status)
        Var 3: single-precision float (4 bytes value + 1 byte status)
        Var 4: double-precision float (8 bytes value + 1 byte status)

    Qualifiers follow the same 0x17/0x28 scheme as CROB (IEEE 1815-2012 Table 4-3).
    The block must have passed _control_block_error, which checks its variation, its
    qualifier and that it holds exactly the declared count of objects.
    """
    points: list[tuple[int, float]] = []
    variation = block.header.variation
    value_size = _AO_VALUE_SIZES[variation]
    count_bytes, index_bytes = _crob_count_index_sizes(block.header.qualifier)
    data = block.data
    count = int.from_bytes(data[0:count_bytes], "little")
    offset = count_bytes

    for _ in range(count):
        index = int.from_bytes(data[offset : offset + index_bytes], "little")
        offset += index_bytes

        raw_value = data[offset : offset + value_size]
        if variation in {AO_VAR_INT32, AO_VAR_INT16}:
            value = float(int.from_bytes(raw_value, "little", signed=True))
        elif variation == AO_VAR_FLOAT32:
            value = float(struct.unpack("<f", raw_value)[0])
        else:
            value = float(struct.unpack("<d", raw_value)[0])

        offset += value_size + 1  # skip request status byte
        points.append((index, value))

    return points


class _ControlStop:
    """Per-request flag: once set, no later control point in the request reaches a handler.

    Created fresh by each of _handle_select, _handle_operate and
    _handle_direct_operate and passed by reference into their block
    processors, so it never outlives the request that created it (#46).
    """

    __slots__ = ("stopped",)

    def __init__(self) -> None:
        self.stopped = False


class _NotACommandResult(Exception):
    """Failure-log key marker: a handler returned something other than a CommandResult (#46)."""


class _InvalidCommandStatus(Exception):
    """Failure-log key marker: a handler's returned status did not coerce (#46)."""


def _coerce_command_status(value: object) -> CommandStatus | None:
    """Accept a status value a handler may reasonably return, or None when it is invalid.

    dnp3.objects.binary_output.CommandStatus mirrors this module's CommandStatus
    numerically (Table 4-2 and Table 11-7 share the same codes) but is a
    separate class, and it is a publicly exported name a handler author may
    import instead of the core one; an instance of either is accepted. A
    plain int (``type(value) is int`` exactly, not a bool or any other int
    subclass such as an unrelated IntEnum) matching a defined value is
    accepted the same way, so a value from an unrelated enum that happens to
    share a numeric value (FunctionCode.CONFIRM is 0, the same as SUCCESS) is
    refused rather than silently coerced (#46).
    """
    if isinstance(value, CommandStatus | ObjectsCommandStatus):
        return CommandStatus(int(value))
    if type(value) is int:
        try:
            return CommandStatus(value)
        except ValueError:
            return None
    return None


def _control_block_error(block: ObjectBlock) -> IIN | None:
    """Return the IIN error bit a control request answers for ``block``, or None when it decodes.

    The control objects are g12v1 and g41v1 to g41v4; any other object is one the control
    path does not know (IIN2.1, IEEE 1815-2012 Table 4-14). A qualifier other than 0x17 or
    0x28, or data that is not exactly the declared count of objects, is malformed (IIN2.2).
    """
    header = block.header
    object_size = _CONTROL_OBJECT_BYTES.get((header.group, header.variation))
    if object_size is None:
        return IIN.OBJECT_UNKNOWN
    try:
        count_bytes, index_bytes = _crob_count_index_sizes(header.qualifier)
    except ValueError:
        return IIN.PARAMETER_ERROR
    data = block.data
    if len(data) < count_bytes:
        return IIN.PARAMETER_ERROR
    count = int.from_bytes(data[:count_bytes], "little")
    if len(data) != count_bytes + count * (index_bytes + object_size):
        return IIN.PARAMETER_ERROR
    return None


def _echo_control_block(block: ObjectBlock, results: list[tuple[int, CommandStatus]]) -> tuple[ObjectBlock, bool]:
    """Echo a control block with object j's status octet set from ``results[j]``.

    The block must have passed _control_block_error. An object whose entry is missing
    or names another index is echoed FORMAT_ERROR rather than given a status that may
    be another object's (each object carries its own status, IEEE 1815-2012 4.4.4.3 Rule 7).

    Returns:
        The echoed block, and True when ``results`` does not match the block's objects.
    """
    count_bytes, index_bytes = _crob_count_index_sizes(block.header.qualifier)
    object_size = index_bytes + _CONTROL_OBJECT_BYTES[(block.header.group, block.header.variation)]
    data = block.data
    count = int.from_bytes(data[:count_bytes], "little")
    echoed = bytearray(data)
    misaligned = len(results) != count

    for position in range(count):
        start = count_bytes + position * object_size
        index = int.from_bytes(data[start : start + index_bytes], "little")
        if position < len(results) and results[position][0] == index:
            status = results[position][1]
        else:
            status = CommandStatus.FORMAT_ERROR
            misaligned = True
        echoed[start + object_size - 1] = int(status)

    return ObjectBlock(header=block.header, data=bytes(echoed)), misaligned


def _write_block_error(block: ObjectBlock) -> IIN | None:
    """Return the IIN error bit a WRITE request answers for ``block``, or None when it applies.

    Only g50v1 (time), g50v3 (LAN-synchronized time, #142) and g80v1
    (internal indications) are objects this outstation writes; any other
    object it does not act on is unknown (IIN2.1, IEEE 1815-2012 Table 4-14).
    A qualifier or count its own source does not fix is malformed (IIN2.2,
    4.5.11): A.23.1.2.3 fixes g50v1 to qualifier 0x07 and count 1; A.23.3
    fixes g50v3 the same way; the Level 1-3 profile tables (Tables 14-2
    through 14-4, WRITE row "00 (start-stop)") fix g80v1 to qualifier 0x00.

    g50v3 additionally requires a RECORD_CURRENT_TIME instant to be applied
    (10.3.3.2 steps a-e); that check depends on outstation state, so it is
    made by ``Outstation._write_block_check``, not here.
    """
    header = block.header
    if (header.group, header.variation) in ((GROUP_TIME_AND_DATE, 1), (GROUP_TIME_AND_DATE, _VARIATION_TIME_LAN_WRITE)):
        if header.qualifier != _WRITE_TIME_QUALIFIER:
            return IIN.PARAMETER_ERROR
        if len(block.data) != 1 + TIMESTAMP_SIZE or block.data[0] != 1:
            return IIN.PARAMETER_ERROR
        return None
    if (header.group, header.variation) == (GROUP_IIN, 1):
        if header.qualifier != 0x00:
            return IIN.PARAMETER_ERROR
        return None
    return IIN.OBJECT_UNKNOWN


@dataclass
class Outstation:
    """DNP3 Outstation implementation.

    Processes requests from a master station and generates responses.
    Uses a Database for point storage and event generation.

    Attributes:
        config: Outstation configuration.
        database: Point database.
        handler: Command handler for control operations.
        time_handler: Called with the decoded time when a master writes
            g50v1 (IEEE 1815-2012 A.23.1.2.3) or g50v3 (A.23.3, LAN time
            sync: the written time plus the elapsed time since the
            RECORD_CURRENT_TIME instant, 10.3.3.2 step e). None (the
            default) accepts and ignores the write, which the clause
            permits for an outstation with its own accurate time source.
            The value comes from the master and is untrusted: it may fall
            outside the range a datetime can represent, and for g50v1 it is
            not adjusted for this outstation's own request-processing delay
            ([F] to [G], 10.3.3.1 h). A g50v3 sum that would not fit the
            48-bit timestamp is refused (IIN2.2) before this handler is
            called. The handler must not raise or block: it runs
            synchronously in process_request, so raising leaves NEED_TIME
            set and answers the WRITE with IIN2.2 instead of applying it
            (#46), and blocking stalls every connection.
        handler_failures: Count of every covered application-code failure
            (a control handler raise or invalid return, or a tracking
            failure after a successful analog output operate), logged or
            not (#46 L3). Monotonic: never reset or decremented.
    """

    config: OutstationConfig = field(default_factory=OutstationConfig)
    database: Database = field(default_factory=Database)
    handler: CommandHandler = field(default_factory=DefaultCommandHandler)
    time_handler: Callable[[DNP3Timestamp], None] | None = None
    handler_failures: int = field(default=0, init=False)
    _state: OutstationStateManager = field(default_factory=OutstationStateManager, init=False)
    _connections_opened: int = field(default=0, init=False, repr=False)
    _failure_log_limiter: FailureLogLimiter = field(default_factory=FailureLogLimiter, init=False, repr=False)
    # RECORD_CURRENT_TIME's receipt instant (monotonic seconds), per peer, for
    # the LAN time-sync procedure (10.3.3.2): one master's FC 24 must not
    # shift or be consumed by another master's g50v3. A peer's entry is
    # absent until its FC 24, and again after its g50v3 WRITE consumes it,
    # another FC 24 from the same peer replaces it, or its connection is
    # released.
    _record_current_time_instants: dict[PeerId, float] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize outstation state."""
        if self.time_handler is not None and not callable(self.time_handler):
            msg = f"time_handler must be callable or None, got {self.time_handler!r}"
            raise TypeError(msg)
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

    def process_request(self, data: bytes, *, peer: PeerId | None = None) -> list[ResponseFragment]:
        """Process a request and generate response fragment(s).

        Args:
            data: Raw request bytes (application layer fragment).
            peer: Identifies the master this request came from. A transport
                serving more than one master must pass this; the default
                (None, mapped to UNSPECIFIED_PEER) is correct for a
                single-master deployment and for every pre-#72 caller.

        Returns:
            List of response fragments. Empty list if no response needed.
            For READ requests with large databases, may return multiple
            fragments respecting max_fragment_size.

        A handler exception is answered the same way a parse failure already
        is: a null response with IIN2.2, so a bug in one handler costs a
        request rather than the connection (#46). IIN2.2 here is a reuse
        beyond its two defined triggers (4.5.11: parse failure, or points
        that do not exist); no other IIN bit fits a caught handler exception
        on an otherwise well-formed request. Until a later fix for #46 adds a
        per-point control guard, a multi-point control that fails partway
        is answered as a whole: earlier points may already have run, but the
        response carries no per-point status. A same-sequence DIRECT_OPERATE
        retry calls the handler again for every point; a same-sequence
        OPERATE retry does not, since the selection was already terminated
        in the ``finally`` around ``_handle_operate``, so every point
        (including one that already ran) answers NO_SELECT with zero
        handler calls. A no-ack function (IEEE 1815-2012 4.4.5) gets none,
        matching _refuse_unframed. Only Exception subclasses are caught: a
        KeyboardInterrupt, SystemExit or asyncio.CancelledError still
        propagates.
        """
        resolved_peer = peer if peer is not None else UNSPECIFIED_PEER
        try:
            request = parse_request(data)
        except Exception:
            # No retry or OPERATE can match what failed to parse, so it ends the sender's selection (Table 4-9).
            self._state.terminate(resolved_peer)
            return [build_null_response(iin=self.iin | IIN.PARAMETER_ERROR)]

        try:
            return self._process_request_fragment(request, resolved_peer, data[2:])
        except Exception:
            _log.exception("Unhandled exception dispatching function %s", request.header.function.name)
            if request.header.function in _NO_ACK_FUNCTIONS:
                return []
            return [build_null_response(iin=self.iin | IIN.PARAMETER_ERROR, seq=request.header.control.seq)]

    def new_connection_id(self) -> int:
        """Return a connection id no transport on this outstation has used yet.

        Selections live on the outstation, so ids must be unique across every
        transport serving it, not only within one.

        Returns:
            The id to put in each PeerId for the new connection.
        """
        self._connections_opened += 1
        return self._connections_opened

    def release_connection(self, connection: int) -> None:
        """Release every SELECT and RECORD_CURRENT_TIME instant made on a transport connection.

        A transport calls this when the connection closes, so a selection or
        a recorded instant cannot outlive the connection that made it.

        Args:
            connection: The connection id the transport put in each PeerId.
        """
        self._state.release_connection(connection)
        expired = [peer for peer in self._record_current_time_instants if peer.connection == connection]
        for peer in expired:
            del self._record_current_time_instants[peer]

    def _process_request_fragment(self, request: RequestFragment, peer: PeerId, body: bytes) -> list[ResponseFragment]:
        """Process a parsed request fragment.

        Args:
            request: Parsed request fragment.
            peer: The peer that sent this request (see process_request).
            body: Raw octets after the function code, compared with the
                SELECT's under IEEE 1815-2012 Table 4-9.

        Returns:
            List of response fragments. Empty list if no response needed.
        """
        header = request.header

        # Track request sequence
        self._state.sequences.last_request_seq = header.control.seq

        return self._apply_select_sequence_rules(request, peer, body)

    def _apply_select_sequence_rules(
        self, request: RequestFragment, peer: PeerId, body: bytes
    ) -> list[ResponseFragment]:
        """Judge a request against the peer's selection in effect (IEEE 1815-2012 Table 4-9).

        Only the requesting peer's selection is read or ended. A CONFIRM leaves
        it in effect: it acknowledges an earlier response rather than following
        the SELECT as a request.
        """
        function = request.header.function
        seq = request.header.control.seq
        self._state.clear_expired_selects(self.config.select_timeout)
        selection = self._state.selection_of(peer)

        if function == FunctionCode.SELECT and selection is not None and seq == selection.sequence:
            if selection.body == body and selection.response is not None:
                return [selection.response]
            return []

        truncation = request.truncation
        if truncation is not None and self._executes(function):
            self._state.terminate(peer)
            return self._refuse_unframed(request, truncation)

        if function == FunctionCode.SELECT:
            selection = self._state.begin_selection(peer, seq, body)
            try:
                response = self._handle_select(request, peer=peer)
            except BaseException:
                # A record with no response would swallow every retry, and its points were never answered.
                self._state.terminate(peer)
                raise
            if selection.points or selection.cancelled:
                self._state.set_response(peer, response)
            else:
                self._state.terminate(peer)
            return [response]

        if function == FunctionCode.OPERATE:
            follows_select = (
                selection is not None
                and seq == (selection.sequence + 1) % (MAX_APP_SEQUENCE + 1)
                and selection.body == body
            )
            if not follows_select:
                # Ended first, so every object answers NO_SELECT and none reaches the handler.
                self._state.terminate(peer)
            try:
                return [self._handle_operate(request, peer=peer)]
            finally:
                # Even if the handler raised, the points it never reached must not stay armed.
                self._state.terminate(peer)

        if function != FunctionCode.CONFIRM:
            self._state.terminate(peer)
        return self._dispatch(request, peer)

    def _refuse_unframed(self, request: RequestFragment, truncation: Truncation) -> list[ResponseFragment]:
        """Answer a request with a block that could not be framed, having executed none of it.

        Later block boundaries are unknown (IEEE 1815-2012 4.2.2.7), so nothing in the
        request runs. An object of unknown width is one the outstation does not know,
        IIN2.1 (Table 4-14); any other failure is a malformed request, IIN2.2 (4.5.11).
        A NO_ACK function is never answered.
        """
        if request.header.function in _NO_ACK_FUNCTIONS:
            return []
        unknown = truncation.reason is TruncationReason.UNKNOWN_WIDTH
        error = IIN.OBJECT_UNKNOWN if unknown else IIN.PARAMETER_ERROR
        return [build_null_response(iin=self.iin | error, seq=request.header.control.seq)]

    def _executes(self, function: FunctionCode) -> bool:
        """Whether a request of this function runs the objects it carries.

        CONFIRM runs none, and an unsupported function answers NO_FUNC_CODE_SUPPORT
        whether or not its objects framed.
        """
        return function in (FunctionCode.SELECT, FunctionCode.OPERATE) or function in self._executors(UNSPECIFIED_PEER)

    def _executors(self, peer: PeerId) -> dict[FunctionCode, _Executor]:
        """The executor of every supported function other than SELECT, OPERATE and CONFIRM.

        WRITE and RECORD_CURRENT_TIME are bound to the requesting peer, so a
        g50v3's recorded instant is looked up and consumed under that same
        peer (see _record_current_time_instants).
        """
        return {
            FunctionCode.READ: self._handle_read,
            FunctionCode.WRITE: _answered(partial(self._handle_write, peer=peer)),
            FunctionCode.DIRECT_OPERATE: _answered(partial(self._handle_direct_operate, peer=peer)),
            FunctionCode.DIRECT_OPERATE_NO_ACK: _unanswered(partial(self._handle_direct_operate, peer=peer)),
            FunctionCode.COLD_RESTART: _answered(self._handle_cold_restart),
            FunctionCode.WARM_RESTART: _answered(self._handle_warm_restart),
            FunctionCode.DELAY_MEASURE: _answered(self._handle_delay_measure),
            FunctionCode.RECORD_CURRENT_TIME: _answered(partial(self._handle_record_current_time, peer=peer)),
            FunctionCode.ENABLE_UNSOLICITED: _answered(self._handle_enable_unsolicited),
            FunctionCode.DISABLE_UNSOLICITED: _answered(self._handle_disable_unsolicited),
            FunctionCode.IMMEDIATE_FREEZE: _answered(partial(self._handle_freeze, clear=False)),
            FunctionCode.FREEZE_CLEAR: _answered(partial(self._handle_freeze, clear=True)),
            FunctionCode.IMMEDIATE_FREEZE_NO_ACK: _unanswered(partial(self._handle_freeze, clear=False)),
            FunctionCode.FREEZE_CLEAR_NO_ACK: _unanswered(partial(self._handle_freeze, clear=True)),
        }

    def _dispatch(self, request: RequestFragment, peer: PeerId) -> list[ResponseFragment]:
        """Dispatch a request that is neither SELECT nor OPERATE by function code."""
        header = request.header
        function = header.function

        if function == FunctionCode.CONFIRM:
            result = self._handle_confirm(request)
            return [result] if result is not None else []
        execute = self._executors(peer).get(function)
        if execute is not None:
            return execute(request)
        return [
            build_null_response(
                iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
                seq=header.control.seq,
            )
        ]

    def _handle_read(self, request: RequestFragment) -> list[ResponseFragment]:
        """Handle READ request, splitting into multiple fragments if needed.

        Event blocks are read without removing them from the buffer (IEEE
        1815-2012 4.1.6, #46): a raise anywhere later in this loop, including
        while encoding a later block, must not cost an event already encoded
        for an earlier one. The keys collected below are removed only once
        every block in the request has built without raising, and before
        `self.iin` is read for the response, so a successful response's IIN
        bits reflect the events it carries as removed, matching a plain pop.
        """
        objects: list[ObjectBlock] = []
        seen_keys: set[_EventKey] = set()
        error_iin = IIN(0)

        for block in request.objects:
            block_objects, block_keys, block_error = self._read_request_block(block, seen_keys)
            objects.extend(block_objects)
            seen_keys.update(block_keys)
            error_iin |= block_error

        if seen_keys:
            # _split_response_objects only packs already-built ObjectBlocks into
            # fragments; it never touches the event buffer, so removing here
            # already covers every fragment the response will be split into.
            self._remove_events_by_key(seen_keys)

        return _split_response_objects(
            objects=objects,
            iin=self.iin | error_iin,
            seq=request.header.control.seq,
            max_fragment_size=self.config.max_fragment_size,
        )

    def _read_request_block(
        self, block: ObjectBlock, seen_keys: Collection[_EventKey]
    ) -> tuple[list[ObjectBlock], list[_EventKey], IIN]:
        """Read one object block of a READ request.

        Args:
            block: The object block to read.
            seen_keys: Event keys already read earlier in this same request
                (by an earlier block), so a request naming one class through
                two groups (g60v2 and g2v0 both name Class 1) does not encode
                the same event twice.

        Returns:
            Tuple of (object blocks, event keys read but not yet removed,
            error IIN). Non-event groups always return an empty key list.
        """
        group = block.header.group
        variation = block.header.variation

        if group == GROUP_CLASS_DATA:
            return self._read_class_data(variation, seen_keys)
        if group == GROUP_BINARY_INPUT:
            objects, error = self._read_binary_inputs(block)
            return objects, [], error
        if group == GROUP_BINARY_INPUT_EVENT:
            objects, keys = self._read_binary_input_events(seen_keys)
            return objects, keys, IIN(0)
        if group == GROUP_BINARY_OUTPUT:
            objects, error = self._read_binary_outputs(block)
            return objects, [], error
        if group == GROUP_ANALOG_INPUT:
            objects, error = self._read_analog_inputs(block)
            return objects, [], error
        if group == GROUP_ANALOG_INPUT_EVENT:
            objects, keys = self._read_analog_input_events(seen_keys)
            return objects, keys, IIN(0)
        if group == GROUP_ANALOG_OUTPUT_STATUS:
            objects, error = self._read_analog_outputs(block)
            return objects, [], error
        if group == GROUP_COUNTER:
            objects, error = self._read_counters(block)
            return objects, [], error
        if group == GROUP_COUNTER_EVENT:
            objects, keys = self._read_counter_events(seen_keys)
            return objects, keys, IIN(0)
        if group == GROUP_FROZEN_COUNTER:
            objects, error = self._read_frozen_counters(block)
            return objects, [], error
        return [], [], IIN.OBJECT_UNKNOWN

    def _read_class_data(
        self, variation: int, seen_keys: Collection[_EventKey] = ()
    ) -> tuple[list[ObjectBlock], list[_EventKey], IIN]:
        """Read class data (Group 60).

        Args:
            variation: Class variation (1=Class 0, 2=Class 1, 3=Class 2, 4=Class 3).
            seen_keys: Event keys already read earlier in this request (see
                _read_request_block); excluded so they are not encoded a
                second time.

        Returns:
            Tuple of (object blocks, event keys read but not yet removed,
            error IIN).
        """
        objects: list[ObjectBlock] = []
        keys: list[_EventKey] = []

        if variation == VAR_CLASS_0:  # Class 0 - all static data
            objects.extend(self._read_all_static_data())
        elif variation == VAR_CLASS_1:  # Class 1 events
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_1, seen_keys)
            objects.extend(class_objects)
            keys.extend(class_keys)
        elif variation == VAR_CLASS_2:  # Class 2 events
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_2, seen_keys)
            objects.extend(class_objects)
            keys.extend(class_keys)
        elif variation == VAR_CLASS_3:  # Class 3 events
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_3, seen_keys)
            objects.extend(class_objects)
            keys.extend(class_keys)
        else:
            return [], [], IIN.OBJECT_UNKNOWN

        return objects, keys, IIN(0)

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

        # Analog Output Status
        ao_points = self.database.get_all_analog_outputs()
        if ao_points:
            objects.extend(self._build_analog_output_blocks(ao_points, self.config.analog_output_static_variation))

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
            serialize=lambda p: BinaryInputFlags(quality=p.quality, state=p.value).to_bytes(),
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, 1),
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
            serialize=lambda p: BinaryOutputFlags(quality=p.quality, state=p.value).to_bytes(),
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, 1),
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
            serialize=_serialize_analog_input,
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, 5),
        )

    def _build_analog_output_blocks(self, points: list[Any], variation: int) -> list[ObjectBlock]:
        """Build ObjectBlocks for analog output status static data (group 40).

        Delegates to _build_static_blocks which splits sparse index sets into
        contiguous runs, each encoded with its own start/stop range header per
        IEEE 1815-2012 Table 4-2.
        """
        return _build_static_blocks(
            group=GROUP_ANALOG_OUTPUT_STATUS,
            variation=variation,
            points=points,
            serialize=lambda p: _serialize_analog_output_status(p, variation),
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, _AO_STATUS_SIZES[variation]),
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
            serialize=lambda p: Counter32(quality=p.quality, value=p.value).to_bytes(),
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, 5),
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
            serialize=lambda p: FrozenCounter32(quality=p.quality, value=p.value).to_bytes(),
            max_points_per_block=_static_block_capacity(self.config.max_fragment_size, 5),
        )

    def _read_class_events(
        self, event_class: EventClass, seen_keys: Collection[_EventKey] = ()
    ) -> tuple[list[ObjectBlock], list[_EventKey]]:
        """Read events for a class without removing them (IEEE 1815-2012 4.1.6, #46).

        A caller must remove the returned keys itself, and only once it
        knows the whole response carrying them was built without raising:
        this method's own encoding (a poison value) or a later block in the
        same request are both raise points a removed-on-read event cannot
        survive.

        Args:
            event_class: Which class's buffer to read.
            seen_keys: (class, serial) keys already read earlier in the same
                response (a request can name one class through two groups,
                e.g. g60v2 and g2v0 both name Class 1); excluded so an event
                already encoded once is not encoded again. Keyed by class as
                well as serial: ClassBuffer.add falls back to its own
                per-class counter when called with no explicit serial
                (event_buffer.py), so a serial alone cannot tell two events
                in different classes apart.

        Events are chunked so no single ObjectBlock exceeds max_fragment_size.
        Per-event wire sizes (1-byte index prefix, 0x17 qualifier assumed):
          g2v1  binary:  1 index + 1 flags                      = 2 bytes
          g32v1 analog:  1 index + 1 flags + 4 value            = 6 bytes
          g22v5 counter: 1 index + 1 flags + 4 value + 6 time   = 12 bytes
        """
        objects: list[ObjectBlock] = []
        serials_and_events = self.database.event_buffer.read_class_events_with_serials(event_class)
        if seen_keys:
            serials_and_events = [
                (serial, event) for serial, event in serials_and_events if (event_class, serial) not in seen_keys
            ]
        keys = [(event_class, serial) for serial, _event in serials_and_events]
        events = [event for _serial, event in serials_and_events]

        # Use concrete event types for discrimination; bool is a subclass of int
        # so value-type checks are not sufficient to separate binary from counter events.
        binary_events = [e for e in events if isinstance(e, BinaryEvent)]
        analog_events = [e for e in events if isinstance(e, AnalogEvent)]
        counter_events = [e for e in events if isinstance(e, CounterEvent)]

        bi_cap = _event_block_capacity(self.config.max_fragment_size, 2)
        ai_cap = _event_block_capacity(self.config.max_fragment_size, 6)
        # g22v5: 1 index + 1 flags + 4 value + 6 timestamp = 12 bytes per event
        ctr_cap = _event_block_capacity(self.config.max_fragment_size, 12)

        for chunk in _chunk_run(binary_events, bi_cap):
            objects.extend(self._build_binary_event_blocks(chunk))
        for chunk in _chunk_run(analog_events, ai_cap):
            objects.extend(self._build_analog_event_blocks(chunk))
        for chunk in _chunk_run(counter_events, ctr_cap):
            objects.extend(self._build_counter_event_blocks(chunk))

        return objects, keys

    def _remove_events_by_key(self, keys: Collection[_EventKey]) -> None:
        """Remove buffered events by (class, serial), one class's buffer at a time.

        EventBuffer.remove_events_by_serials matches a bare serial against
        every class's buffer, which is correct only when a serial is unique
        across the whole buffer. That is true of a serial the EventBuffer
        itself assigned, but not of one a ClassBuffer assigned on its own
        (event_buffer.py): two events in different classes can then share a
        serial, and removing by serial alone would remove both, even though
        only one was ever read into a response. Removing through each key's
        own ClassBuffer keeps the two apart.
        """
        buffer = self.database.event_buffer
        by_class: dict[EventClass, set[int]] = {}
        for event_class, serial in keys:
            by_class.setdefault(event_class, set()).add(serial)
        for event_class, serials in by_class.items():
            if event_class == EventClass.CLASS_1:
                buffer.class1.remove_by_serials(serials)
            elif event_class == EventClass.CLASS_2:
                buffer.class2.remove_by_serials(serials)
            elif event_class == EventClass.CLASS_3:
                buffer.class3.remove_by_serials(serials)

    @staticmethod
    def _event_framing(events: list[Any]) -> tuple[int, bytes, int]:
        """Compute shared index-prefix framing fields for an event block.

        All three event builders (binary, analog, counter) choose the same
        index size, count-field encoding, and qualifier code from the maximum
        point index in the event list.  This helper centralises that choice.

        Args:
            events: Non-empty list of events; callers must guard against empty.

        Returns:
            Tuple of (index_size, count_data, qualifier) where:
              - index_size: bytes per index prefix (1 or 2)
              - count_data: serialised count field (1 or 2 bytes, little-endian)
              - qualifier: 0x17 (1-byte) or 0x28 (2-byte) per IEEE 1815-2012
        """
        max_index = max(e.index for e in events)
        if max_index <= MAX_1_BYTE_INDEX:
            return 1, CountRange(count=len(events)).to_bytes_1(), 0x17
        return 2, CountRange(count=len(events)).to_bytes_2(), 0x28

    def _build_binary_event_blocks(self, events: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for binary events."""
        if not events:
            return []

        data = bytearray()
        index_size, count_data, qualifier = self._event_framing(events)

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            # g2v1 format: 1 byte flags (delegated to BinaryInputEvent.to_bytes())
            data.extend(BinaryInputEvent(quality=event.quality, state=event.value).to_bytes())

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
        index_size, count_data, qualifier = self._event_framing(events)

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            # g32v1 format: 1 byte flags + 4 bytes signed value, clamped over 11.6.1.1 (#159).
            data.extend(_serialize_analog_input_event(event))

        header = ObjectHeader(
            group=GV_ANALOG_INPUT_EVENT[0],
            variation=GV_ANALOG_INPUT_EVENT[1],
            qualifier=qualifier,
        )
        return [ObjectBlock(header=header, data=count_data + bytes(data))]

    def _build_counter_event_blocks(self, events: list[Any]) -> list[ObjectBlock]:
        """Build object blocks for counter events.

        Emits g22v5: 32-bit counter event with 48-bit timestamp. Per-event wire
        size including the 1-byte index prefix is 12 bytes (1 index + 1 flag +
        4 value + 6 timestamp), matching the ctr_cap capacity calculation in
        _read_class_events. The timestamp is taken from the event (always set
        at change time by database.update_counter/increment_counter); the
        DNP3Timestamp.now() fallback is a defensive last resort that should
        never fire under normal operation.
        """
        if not events:
            return []

        data = bytearray()
        index_size, count_data, qualifier = self._event_framing(events)

        for event in events:
            if index_size == 1:
                data.append(event.index & 0xFF)
            else:
                data.extend(event.index.to_bytes(2, "little"))
            ts = event.timestamp if event.timestamp is not None else DNP3Timestamp.now()
            data.extend(CounterEvent32Time(quality=event.quality, value=event.value, timestamp=ts).to_bytes())

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

    def _read_binary_input_events(
        self, seen_keys: Collection[_EventKey] = ()
    ) -> tuple[list[ObjectBlock], list[_EventKey]]:
        """Read all binary input events, without removing them (see _read_class_events)."""
        return self._read_class_events(EventClass.CLASS_1, seen_keys)

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

    def _read_analog_input_events(
        self, seen_keys: Collection[_EventKey] = ()
    ) -> tuple[list[ObjectBlock], list[_EventKey]]:
        """Read all analog input events, without removing them (see _read_class_events)."""
        return self._read_class_events(EventClass.CLASS_2, seen_keys)

    def _read_analog_outputs(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read analog output status (group 40) for a request block.

        IEEE 1815-2012 4.2.2.7.2.1: variation 0 answers in the configured
        default variation. 4.2.2.7.2.2: 1-4 are served as requested; any
        other variation is unknown.
        """
        variation = block.header.variation
        if variation == 0:
            variation = self.config.analog_output_static_variation
        elif variation not in _AO_STATUS_SIZES:
            return [], IIN.OBJECT_UNKNOWN

        points = self.database.get_all_analog_outputs()
        if not points:
            return [], IIN(0)
        return self._build_analog_output_blocks(points, variation), IIN(0)

    def _read_counters(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read counters for a request block."""
        points = self.database.get_all_counters()
        if not points:
            return [], IIN(0)
        return self._build_counter_blocks(points), IIN(0)

    def _read_counter_events(self, seen_keys: Collection[_EventKey] = ()) -> tuple[list[ObjectBlock], list[_EventKey]]:
        """Read all counter events, without removing them (see _read_class_events)."""
        return self._read_class_events(EventClass.CLASS_3, seen_keys)

    def _read_frozen_counters(self, block: ObjectBlock) -> tuple[list[ObjectBlock], IIN]:
        """Read frozen counters for a request block."""
        points = self.database.get_all_frozen_counters()
        if not points:
            return [], IIN(0)
        return self._build_frozen_counter_blocks(points), IIN(0)

    def _handle_write(self, request: RequestFragment, *, peer: PeerId = UNSPECIFIED_PEER) -> ResponseFragment:
        """Handle WRITE request.

        Rule W is this outstation's own policy, mirroring #130's control
        rule (not a requirement of IEEE 1815-2012 4.4.4.3, which governs
        SELECT/OPERATE): every block is checked before any is applied. A
        request holding any block this outstation cannot write delivers
        nothing and clears nothing, and the response carries the IIN bit of
        the first failing block.

        Every time_handler call happens before any IIN bit is cleared,
        whatever order the blocks arrived in, so a raising handler (see
        time_handler's docstring) leaves NEED_TIME and DEVICE_RESTART
        exactly as they were.

        Supports g50v1 (deliver the time to time_handler, then clear
        NEED_TIME), g50v3 (deliver the written time plus elapsed time since
        ``peer``'s RECORD_CURRENT_TIME instant, then clear NEED_TIME and
        consume that peer's instant, 10.3.3.2) and g80v1 (clear
        DEVICE_RESTART or NEED_TIME).

        A g50v3 block's delivered time is computed once, in the check pass,
        and reused for the handler call below: a second clock read there
        could push a sum the check just accepted past the 48-bit width.
        """
        seq = request.header.control.seq
        delivered_times: list[DNP3Timestamp | None] = []
        for block in request.objects:
            error, delivered = self._write_block_check(block, peer=peer)
            if error is not None:
                return build_null_response(iin=self.iin | error, seq=seq)
            delivered_times.append(delivered)

        for block, delivered in zip(request.objects, delivered_times, strict=True):
            if block.header.group == GROUP_TIME_AND_DATE and block.header.variation == 1:
                self._call_time_handler(block)
            elif block.header.group == GROUP_TIME_AND_DATE and block.header.variation == _VARIATION_TIME_LAN_WRITE:
                self._call_time_handler_g50v3(delivered)

        for block in request.objects:
            if block.header.group == GROUP_TIME_AND_DATE and block.header.variation == 1:
                self._state.clear_need_time()
            elif block.header.group == GROUP_TIME_AND_DATE and block.header.variation == _VARIATION_TIME_LAN_WRITE:
                self._state.clear_need_time()
                self._record_current_time_instants.pop(peer, None)
            elif block.header.group == GROUP_IIN and block.header.variation == 1:
                self._handle_write_iin(block)

        return build_null_response(
            iin=self.iin,
            seq=seq,
        )

    def _write_block_check(
        self, block: ObjectBlock, *, peer: PeerId = UNSPECIFIED_PEER
    ) -> tuple[IIN | None, DNP3Timestamp | None]:
        """Return the IIN error bit a WRITE answers for ``block``, or the g50v3 delivered time.

        Delegates the block-only checks (qualifier, count) to
        ``_write_block_error``. Adds the checks that depend on outstation
        state: a g50v3 block needs ``peer``'s own RECORD_CURRENT_TIME
        instant recorded, or it has nothing to compute the delivered time
        from (10.3.3.2 step e); and the written time plus the elapsed time
        since that instant must fit the 48-bit timestamp width, or there is
        nothing a conforming DNP3Timestamp can deliver. Both answer IIN2.2
        the same as a bad qualifier.

        For a g50v3 block that passes, the second element is the delivered
        time computed from this single clock read, so the handler call
        later in ``_handle_write`` delivers exactly the value this check
        accepted rather than reading the clock again. For every other
        block, and for any failing block, the second element is None.
        """
        error = _write_block_error(block)
        if error is not None:
            return error, None
        is_g50v3 = block.header.group == GROUP_TIME_AND_DATE and block.header.variation == _VARIATION_TIME_LAN_WRITE
        if not is_g50v3:
            return None, None
        recorded = self._record_current_time_instants.get(peer)
        if recorded is None:
            return IIN.PARAMETER_ERROR, None
        written = DNP3Timestamp.from_bytes(block.data[1:])
        elapsed_ms = round((time.monotonic() - recorded) * 1000)
        delivered_ms = written.milliseconds + elapsed_ms
        if delivered_ms > _MAX_TIMESTAMP_MS:
            return IIN.PARAMETER_ERROR, None
        return None, DNP3Timestamp(delivered_ms)

    def _call_time_handler(self, block: ObjectBlock) -> None:
        """Decode g50v1's timestamp and call time_handler. Clears no state.

        The block has already passed _write_block_error, so its data is
        exactly the count byte and one 6-octet timestamp (A.23.1.2.3). Kept
        separate from clearing NEED_TIME so every handler call in a WRITE
        happens before _handle_write applies any IIN bit change: if the
        handler raises, process_request answers IIN2.2 (#46) and no bit in
        this WRITE has been cleared yet, whatever order the blocks arrived
        in.

        Args:
            block: g50v1 object block with qualifier 0x07, count 1.
        """
        if self.time_handler is None:
            return
        timestamp = DNP3Timestamp.from_bytes(block.data[1:])
        self.time_handler(timestamp)

    def _call_time_handler_g50v3(self, delivered: DNP3Timestamp | None) -> None:
        """Call time_handler with ``delivered``, g50v3's already-checked time.

        Clears no state and does not consume the instant (see
        _handle_write). ``delivered`` is the value ``_write_block_check``
        computed from IEEE 1815-2012 10.3.3.2 step e (the written time plus
        the milliseconds from [B], the recorded instant, to [C], the instant
        the clock was read): calling this with anything but that value
        would let a WRITE deliver a time the 48-bit check never accepted.
        Kept separate from clearing NEED_TIME and consuming the instant so,
        as with g50v1, a raising handler leaves both unchanged.

        Args:
            delivered: The time ``_write_block_check`` computed for this
                block, or None if reached without one.
        """
        if self.time_handler is None:
            return
        if delivered is None:
            # _write_block_check already refused any block reaching here
            # with no computed delivered time.
            msg = "_call_time_handler_g50v3 reached with no delivered time"
            raise RuntimeError(msg)
        self.time_handler(delivered)

    def _handle_write_iin(self, block: ObjectBlock) -> None:
        """Apply a WRITE of g80v1 (Internal Indications): clear a bit written 0.

        The block has already passed _write_block_error, so its qualifier is
        0x00 (1-byte start-stop range) and its data holds at least the start
        and stop octets. Per IEEE 1815-2012 4.5.5, only a bit written 0 is
        acted on; the master cannot set a bit through WRITE.

        Args:
            block: g80v1 object block with qualifier 0x00.
        """
        data = block.data
        start = data[0]
        stop = data[1]

        # The bit data follows the range bytes; each bit corresponds to an IIN bit.
        bit_offset = MIN_IIN_WRITE_DATA
        for bit_index in range(start, stop + 1):
            byte_pos = bit_offset + (bit_index - start) // 8
            bit_pos = (bit_index - start) % 8
            if byte_pos >= len(data):
                break

            bit_value = (data[byte_pos] >> bit_pos) & 1
            if bit_value != 0:
                continue

            if bit_index == IIN_BIT_DEVICE_RESTART:
                self._state.clear_restart()
            elif bit_index == IIN_BIT_NEED_TIME:
                self._state.clear_need_time()

    def _refuse_undecodable(self, request: RequestFragment) -> ResponseFragment | None:
        """Answer a control request carrying a block the control path cannot use, or return None.

        Every block is checked before any point runs, and the answer carries no objects
        (IEEE 1815-2012 4.4.4.3 Rule 6 item 1) and the IIN bit of the first failing block (Rule 7).
        """
        for block in request.objects:
            error = _control_block_error(block)
            if error is not None:
                return build_null_response(iin=self.iin | error, seq=request.header.control.seq)
        return None

    def _handle_select(self, request: RequestFragment, *, peer: PeerId = UNSPECIFIED_PEER) -> ResponseFragment:
        """Handle SELECT request."""
        block_results: list[list[tuple[int, CommandStatus]]] = []
        seq = request.header.control.seq
        stop = _ControlStop()

        self._state.clear_expired_selects(self.config.select_timeout)

        refusal = self._refuse_undecodable(request)
        if refusal is not None:
            return refusal

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results.append(self._process_crob_select(block, seq, peer=peer, stop=stop))
            elif block.header.group == GROUP_ANALOG_OUTPUT:
                block_results.append(self._process_ao_select(block, seq, peer=peer, stop=stop))

        if any(status != CommandStatus.SUCCESS for results in block_results for _, status in results):
            # A non-zero status in any object cancels the entire selection (IEEE 1815-2012 4.4.4.3 Rule 3).
            self._state.cancel_points(peer)

        return self._build_control_response(request, block_results)

    def _process_crob_select(
        self,
        block: ObjectBlock,
        seq: int,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.SELECT,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process CROB SELECT.

        Delegates parsing to _parse_crob_block which handles qualifier sizing,
        buffer validation, and control-code decoding.  Rejected entries are
        forwarded with their status.  A point another peer holds returns
        BLOCKED_OTHER_MASTER without reaching the handler.  Other valid entries
        are dispatched to the handler and, on success, stored as this peer's
        pending SELECT state. Once ``stop`` is set (a raise or a bad return
        from an earlier point in this request), every later point is
        UNDEFINED without being dispatched (4.4.4.3 Rule 5; #46).
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if stop.stopped:
                results.append((crob.index, CommandStatus.UNDEFINED))
                continue

            if crob.control_code is None:
                results.append((crob.index, crob.status))
                continue

            if self._state.held_by_other_peer(crob.index, peer, self.config.select_timeout):
                results.append((crob.index, CommandStatus.BLOCKED_OTHER_MASTER))
                continue

            code = crob.control_code
            status = self._run_control_point(
                partial(
                    self.handler.select_binary_output,
                    index=crob.index,
                    code=code,
                    count=crob.op_count,
                    on_time=crob.on_time,
                    off_time=crob.off_time,
                ),
                function=function,
                handler_method="select_binary_output",
                index=crob.index,
                peer=peer,
                stop=stop,
            )

            if status == CommandStatus.SUCCESS:
                select_state = SelectState(
                    index=crob.index,
                    is_binary=True,
                    control_code=code,
                    count=crob.op_count,
                    on_time=crob.on_time,
                    off_time=crob.off_time,
                    sequence=seq,
                )
                # The store stamps the point with the selection's start time.
                self._state.add_select(select_state, peer=peer)

            results.append((crob.index, status))

        return results

    def _log_handler_failure(
        self,
        *,
        function: FunctionCode,
        handler_method: str,
        exception_type: type[BaseException],
        exc_info: BaseException | None,
        message: str,
        args: tuple[object, ...],
    ) -> None:
        """Log one covered application-code failure, rate-limited per key (#46 L1-L3).

        Every covered failure increments ``handler_failures`` whether or
        not it is logged (L3). At most one ERROR record per (function,
        handler method, exception type) key is written per
        ``WINDOW_SECONDS`` (L2); the record after a window reports how
        many were suppressed during it.
        """
        self.handler_failures += 1
        key: FailureKey = (function, handler_method, exception_type)
        suppressed = self._failure_log_limiter.record(key)
        if suppressed is None:
            return
        if suppressed:
            message = f"{message} (%d suppressed in the last {WINDOW_SECONDS:.0f}s)"
            args = (*args, suppressed)
        _log.error(message, *args, exc_info=exc_info)

    def _run_control_point(
        self,
        call: Callable[[], CommandResult],
        *,
        function: FunctionCode,
        handler_method: str = "",
        index: int,
        peer: PeerId = UNSPECIFIED_PEER,
        stop: "_ControlStop",
    ) -> CommandStatus:
        """Call one control handler method for one point, guarding a raise or a bad return.

        Returns the point's status, coerced through ``_coerce_command_status``.
        A raise, or a return whose status does not coerce, gives the point
        UNDEFINED (127, Table 11-7) and sets ``stop``, so no later handler
        call is made in this request, across blocks (4.4.4.3 Rule 5; #46).
        The status is not proof the point did nothing: a handler that acts
        and then raises is still reported as not accepted (Rule 7; the
        CommandHandler docstring states the contract). Each failure is
        logged through ``_log_handler_failure``, rate-limited per
        (function, handler method, exception type) (#46 L1-L3).
        """
        try:
            result = call()
        except Exception as exc:
            self._log_handler_failure(
                function=function,
                handler_method=handler_method,
                exception_type=type(exc),
                exc_info=exc,
                message="Control handler raised for %s point %d, peer %s",
                args=(function.name, index, peer),
            )
            stop.stopped = True
            return CommandStatus.UNDEFINED
        if not isinstance(result, CommandResult):
            self._log_handler_failure(
                function=function,
                handler_method=handler_method,
                exception_type=_NotACommandResult,
                exc_info=None,
                message="Control handler returned %r for %s point %d, not a CommandResult, peer %s",
                args=(result, function.name, index, peer),
            )
            stop.stopped = True
            return CommandStatus.UNDEFINED
        status = _coerce_command_status(result.status)
        if status is None:
            self._log_handler_failure(
                function=function,
                handler_method=handler_method,
                exception_type=_InvalidCommandStatus,
                exc_info=None,
                message="Control handler returned %r for %s point %d, status not a valid CommandStatus, peer %s",
                args=(result, function.name, index, peer),
            )
            stop.stopped = True
            return CommandStatus.UNDEFINED
        return status

    def _handle_operate(self, request: RequestFragment, *, peer: PeerId = UNSPECIFIED_PEER) -> ResponseFragment:
        """Handle OPERATE request."""
        block_results: list[list[tuple[int, CommandStatus]]] = []
        seq = request.header.control.seq
        stop = _ControlStop()

        # Clear expired selects first
        self._state.clear_expired_selects(self.config.select_timeout)

        refusal = self._refuse_undecodable(request)
        if refusal is not None:
            return refusal

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results.append(self._process_crob_operate(block, seq, peer=peer, stop=stop))
            elif block.header.group == GROUP_ANALOG_OUTPUT:
                block_results.append(self._process_ao_operate(block, peer=peer, stop=stop))

        return self._build_control_response(request, block_results)

    def _process_crob_operate(
        self,
        block: ObjectBlock,
        seq: int,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.OPERATE,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process CROB OPERATE.

        Delegates parsing to _parse_crob_block.  Rejected entries are forwarded
        with their status.  Valid entries are checked against this peer's stored
        SELECT state only; mismatches return NO_SELECT and clear this peer's
        pending state. Once ``stop`` is set, every later point is UNDEFINED
        without being dispatched (4.4.4.3 Rule 5; #46).
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if stop.stopped:
                results.append((crob.index, CommandStatus.UNDEFINED))
                continue

            if crob.control_code is None:
                results.append((crob.index, crob.status))
                continue

            select_state = self._state.get_select(crob.index, peer=peer)
            if select_state is None:
                results.append((crob.index, CommandStatus.NO_SELECT))
                continue

            if not select_state.matches_binary(
                crob.index, crob.control_code, crob.op_count, crob.on_time, crob.off_time
            ):
                results.append((crob.index, CommandStatus.NO_SELECT))
                self._state.remove_select(crob.index, peer=peer)
                continue

            code = crob.control_code
            status = self._run_control_point(
                partial(
                    self.handler.operate_binary_output,
                    index=crob.index,
                    code=code,
                    count=crob.op_count,
                    on_time=crob.on_time,
                    off_time=crob.off_time,
                    select_sequence=select_state.sequence,
                ),
                function=function,
                handler_method="operate_binary_output",
                index=crob.index,
                peer=peer,
                stop=stop,
            )

            self._state.remove_select(crob.index, peer=peer)
            results.append((crob.index, status))

        return results

    def _process_ao_select(
        self,
        block: ObjectBlock,
        seq: int,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.SELECT,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process Analog Output SELECT (Group 41).

        A point another peer holds returns BLOCKED_OTHER_MASTER without reaching
        the handler. Other points are dispatched to the handler and, on success,
        stored as this peer's pending SELECT state under group 41, so a CROB
        selection at the same index is a separate point. Once ``stop`` is set,
        every later point is UNDEFINED without being dispatched (4.4.4.3 Rule
        5; #46).
        """
        points = _parse_ao_block(block)
        results: list[tuple[int, CommandStatus]] = []

        for index, value in points:
            if stop.stopped:
                results.append((index, CommandStatus.UNDEFINED))
                continue

            if self._state.held_by_other_peer(index, peer, self.config.select_timeout, group=GROUP_ANALOG_OUTPUT):
                results.append((index, CommandStatus.BLOCKED_OTHER_MASTER))
                continue

            status = self._run_control_point(
                partial(self.handler.select_analog_output, index=index, value=value),
                function=function,
                handler_method="select_analog_output",
                index=index,
                peer=peer,
                stop=stop,
            )

            if status == CommandStatus.SUCCESS:
                select_state = SelectState(index=index, is_binary=False, analog_value=value, sequence=seq)
                self._state.add_select(select_state, peer=peer, group=GROUP_ANALOG_OUTPUT)

            results.append((index, status))

        return results

    def _process_ao_operate(
        self,
        block: ObjectBlock,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.OPERATE,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process Analog Output OPERATE (Group 41).

        Each point is checked against this peer's group 41 selection only; a
        missing or mismatched selection returns NO_SELECT without reaching the
        handler. Once ``stop`` is set, every later point is UNDEFINED without
        being dispatched (4.4.4.3 Rule 5; #46).
        """
        points = _parse_ao_block(block)
        results: list[tuple[int, CommandStatus]] = []

        for index, value in points:
            if stop.stopped:
                results.append((index, CommandStatus.UNDEFINED))
                continue

            select_state = self._state.get_select(index, peer=peer, group=GROUP_ANALOG_OUTPUT)
            if select_state is None or not select_state.matches_analog(index, value):
                results.append((index, CommandStatus.NO_SELECT))
                self._state.remove_select(index, peer=peer, group=GROUP_ANALOG_OUTPUT)
                continue

            status = self._run_control_point(
                partial(
                    self.handler.operate_analog_output, index=index, value=value, select_sequence=select_state.sequence
                ),
                function=function,
                handler_method="operate_analog_output",
                index=index,
                peer=peer,
                stop=stop,
            )
            if status == CommandStatus.SUCCESS:
                self._track_ao_command(index, value, function=function, peer=peer)

            self._state.remove_select(index, peer=peer, group=GROUP_ANALOG_OUTPUT)
            results.append((index, status))

        return results

    def _handle_direct_operate(self, request: RequestFragment, *, peer: PeerId = UNSPECIFIED_PEER) -> ResponseFragment:
        """Handle DIRECT_OPERATE request.

        ``peer`` carries no selection state on this path (DIRECT_OPERATE
        needs no prior SELECT); it is threaded through only so a failure
        log names which master's request caused it (#46 L1).
        """
        refusal = self._refuse_undecodable(request)
        if refusal is not None:
            return refusal

        block_results: list[list[tuple[int, CommandStatus]]] = []
        function = request.header.function
        stop = _ControlStop()

        for block in request.objects:
            if block.header.group == GROUP_CROB and block.header.variation == 1:
                block_results.append(self._process_crob_direct_operate(block, function=function, peer=peer, stop=stop))
            elif block.header.group == GROUP_ANALOG_OUTPUT:
                block_results.append(self._process_ao_direct_operate(block, function=function, peer=peer, stop=stop))

        return self._build_control_response(request, block_results)

    def _process_crob_direct_operate(
        self,
        block: ObjectBlock,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.DIRECT_OPERATE,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process CROB DIRECT_OPERATE.

        Delegates parsing to _parse_crob_block.  Rejected entries are forwarded
        with their status; valid entries are dispatched immediately to the handler with no
        prior SELECT required. Once ``stop`` is set, every later point is
        UNDEFINED without being dispatched (4.4.4.3 Rule 5; #46).
        """
        results: list[tuple[int, CommandStatus]] = []

        for crob in _parse_crob_block(block):
            if stop.stopped:
                results.append((crob.index, CommandStatus.UNDEFINED))
                continue

            if crob.control_code is None:
                results.append((crob.index, crob.status))
                continue

            code = crob.control_code
            status = self._run_control_point(
                partial(
                    self.handler.direct_operate_binary_output,
                    index=crob.index,
                    code=code,
                    count=crob.op_count,
                    on_time=crob.on_time,
                    off_time=crob.off_time,
                ),
                function=function,
                handler_method="direct_operate_binary_output",
                index=crob.index,
                peer=peer,
                stop=stop,
            )

            results.append((crob.index, status))

        return results

    def _process_ao_direct_operate(
        self,
        block: ObjectBlock,
        *,
        peer: PeerId = UNSPECIFIED_PEER,
        function: FunctionCode = FunctionCode.DIRECT_OPERATE,
        stop: "_ControlStop",
    ) -> list[tuple[int, CommandStatus]]:
        """Process Analog Output DIRECT_OPERATE (Group 41).

        Each object _parse_ao_block returns is dispatched immediately to the
        handler with no prior SELECT required. Once ``stop`` is set, every
        later point is UNDEFINED without being dispatched (4.4.4.3 Rule 5;
        #46).
        """
        points = _parse_ao_block(block)
        results: list[tuple[int, CommandStatus]] = []
        for index, value in points:
            if stop.stopped:
                results.append((index, CommandStatus.UNDEFINED))
                continue

            status = self._run_control_point(
                partial(self.handler.direct_operate_analog_output, index=index, value=value),
                function=function,
                handler_method="direct_operate_analog_output",
                index=index,
                peer=peer,
                stop=stop,
            )
            if status == CommandStatus.SUCCESS:
                self._track_ao_command(index, value, function=function, peer=peer)
            results.append((index, status))
        return results

    def _track_ao_command(
        self,
        index: int,
        value: float,
        *,
        function: FunctionCode = FunctionCode.OPERATE,
        peer: PeerId = UNSPECIFIED_PEER,
    ) -> None:
        """Store a commanded analog output value as its status (clause 11.9.2.2).

        Called after DIRECT_OPERATE, DIRECT_OPERATE_NO_ACK or OPERATE of
        group 41 succeeds. A no-op when the Database has no point at index or
        the point opts out with config.track_commands = False. A NaN value
        (g41v3/v4) is refused rather than synthesized: the point keeps its
        prior value and the refusal is logged once, and is not rate-limited
        (it is a bounded per-call refusal, not an unbounded failure).
        Any other exception the Database raises, including from the lookup
        itself, is caught, counted and rate-limited through
        ``_log_handler_failure`` like a control handler failure: the output
        already operated, so the point's control status stays SUCCESS even
        though its tracked value could not be stored (#46 L1-L3). The
        commanded value never appears in a log message: it comes from the
        request and this module logs no master-supplied bytes.
        """
        try:
            point = self.database.get_analog_output(index)
        except Exception as exc:
            self._log_handler_failure(
                function=function,
                handler_method="get_analog_output",
                exception_type=type(exc),
                exc_info=exc,
                message="analog output %d: lookup failed after operate, tracked value not stored, function %s, peer %s",
                args=(index, function.name, peer),
            )
            return
        if point is None or not point.config.track_commands:
            return
        try:
            self.database.update_analog_output(index, value)
        except ValueError:
            _log.warning("analog output %d: commanded value rejected, status unchanged", index)
        except Exception as exc:
            self._log_handler_failure(
                function=function,
                handler_method="update_analog_output",
                exception_type=type(exc),
                exc_info=exc,
                message="analog output %d: commanded value not stored after operate, function %s, peer %s",
                args=(index, function.name, peer),
            )

    def _build_control_response(
        self,
        request: RequestFragment,
        block_results: list[list[tuple[int, CommandStatus]]],
    ) -> ResponseFragment:
        """Build response for control operations.

        The response echoes the request's object headers and objects, which the master
        compares octet for octet (IEEE 1815-2012 4.4.4.3 Rule 8), with each object's
        status octet set to its own result (Rule 7).
        Any FORMAT_ERROR status, or a result list that does not match its block, also
        sets IIN.PARAMETER_ERROR in the response header.

        Args:
            request: The original control request; every block passed _control_block_error.
            block_results: One list per block of request.objects, holding one
                (index, status) per object of that block in wire order.
        """
        parameter_error = len(block_results) != len(request.objects)
        objects: list[ObjectBlock] = []

        for position, block in enumerate(request.objects):
            results = block_results[position] if position < len(block_results) else []
            echoed, misaligned = _echo_control_block(block, results)
            objects.append(echoed)
            parameter_error = parameter_error or misaligned
            parameter_error = parameter_error or any(status == CommandStatus.FORMAT_ERROR for _, status in results)

        iin = self.iin
        if parameter_error:
            iin = iin | IIN.PARAMETER_ERROR

        return build_response(
            objects=tuple(objects),
            iin=iin,
            seq=request.header.control.seq,
        )

    def _build_delay_response(
        self,
        restart_fn: Callable[[], int | None],
        request: RequestFragment,
    ) -> ResponseFragment:
        """Build a g52v2 time-delay response for COLD_RESTART and WARM_RESTART.

        Both handlers are identical except for the callable that produces the
        delay value; this helper eliminates the duplication.

        Args:
            restart_fn: handler.cold_restart or handler.warm_restart.
            request: The original restart request (needed for seq and IIN).

        Returns:
            Response with a g52v2 time-delay block, or a NO_FUNC_CODE_SUPPORT
            null response when restart_fn returns None.
        """
        delay = restart_fn()
        if delay is None:
            return build_null_response(
                iin=self.iin | IIN.NO_FUNC_CODE_SUPPORT,
                seq=request.header.control.seq,
            )

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

    def _handle_cold_restart(self, request: RequestFragment) -> ResponseFragment:
        """Handle COLD_RESTART request."""
        return self._build_delay_response(self.handler.cold_restart, request)

    def _handle_warm_restart(self, request: RequestFragment) -> ResponseFragment:
        """Handle WARM_RESTART request."""
        return self._build_delay_response(self.handler.warm_restart, request)

    def _handle_delay_measure(self, request: RequestFragment) -> ResponseFragment:
        """Handle DELAY_MEASURE request for time sync.

        Does not clear NEED_TIME: the clock is set at the WRITE that follows
        (IEEE 1815-2012 10.3.3.1 h), and 4.5.5 clears NEED_TIME only on a
        time synchronization message or a written IIN1.4, neither of which
        this request is.
        """
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

        return build_response(
            objects=(block,),
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_record_current_time(
        self, request: RequestFragment, *, peer: PeerId = UNSPECIFIED_PEER
    ) -> ResponseFragment:
        """Handle RECORD_CURRENT_TIME (FC 24) for LAN time sync (IEEE 1815-2012
        10.3.3.2, 4.4.16.1 Rule 2 for a TCP/IP outstation that sets NEED_TIME).

        Records this instant [B] for ``peer`` on a monotonic clock, so the
        g50v3 WRITE that should follow from the SAME peer can compute the
        elapsed time to [C] (10.3.3.2 step e). Keyed by peer so one master's
        RECORD_CURRENT_TIME never shifts or is consumed by another's g50v3.
        A later RECORD_CURRENT_TIME from ``peer`` with no intervening WRITE
        discards its earlier instant, per 10.3.3.2's requirement to discard a
        stale recorded time on a repeat, matching this assignment's
        overwrite.
        """
        self._record_current_time_instants[peer] = time.monotonic()
        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _process_unsolicited_class_request(
        self,
        request: RequestFragment,
        action: Callable[[EventClass], None],
    ) -> ResponseFragment:
        """Shared core for ENABLE_UNSOLICITED and DISABLE_UNSOLICITED.

        Both handlers walk the same g60-class object list and differ only in
        the per-class action (enable vs disable); this helper captures the
        shared iteration and null-response build.

        Args:
            request: The ENABLE or DISABLE unsolicited request.
            action: Called with the EventClass for each recognised class object.

        Returns:
            Null response with current IIN.
        """
        for block in request.objects:
            if block.header.group == GROUP_CLASS_DATA:
                if block.header.variation == VAR_CLASS_1:
                    action(EventClass.CLASS_1)
                elif block.header.variation == VAR_CLASS_2:
                    action(EventClass.CLASS_2)
                elif block.header.variation == VAR_CLASS_3:
                    action(EventClass.CLASS_3)

        return build_null_response(
            iin=self.iin,
            seq=request.header.control.seq,
        )

    def _handle_enable_unsolicited(self, request: RequestFragment) -> ResponseFragment:
        """Handle ENABLE_UNSOLICITED request."""
        return self._process_unsolicited_class_request(request, self._state.unsolicited.enable_class)

    def _handle_disable_unsolicited(self, request: RequestFragment) -> ResponseFragment:
        """Handle DISABLE_UNSOLICITED request."""
        return self._process_unsolicited_class_request(request, self._state.unsolicited.disable_class)

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

        Events are read without removing them (IEEE 1815-2012 4.6.6, #46): a
        raise while encoding a later class must not cost an event already
        encoded for an earlier one. There is no request here to answer, so a
        raise still propagates to the caller, unlike a READ (#155); the keys below
        are removed only once every class has been read and encoded without
        raising, and before `self.iin` is read for the response, matching a
        plain pop.

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
        seen_keys: set[_EventKey] = set()

        if unsolicited.class_1_enabled and buffer.class1.count > 0:
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_1, seen_keys)
            objects.extend(class_objects)
            seen_keys.update(class_keys)
        if unsolicited.class_2_enabled and buffer.class2.count > 0:
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_2, seen_keys)
            objects.extend(class_objects)
            seen_keys.update(class_keys)
        if unsolicited.class_3_enabled and buffer.class3.count > 0:
            class_objects, class_keys = self._read_class_events(EventClass.CLASS_3, seen_keys)
            objects.extend(class_objects)
            seen_keys.update(class_keys)

        if not objects:
            return None

        self._remove_events_by_key(seen_keys)

        # Generate unsolicited response
        seq = self._state.sequences.next_unsolicited_seq()
        unsolicited.pending_confirm = True
        unsolicited.confirm_sequence = seq

        return build_unsolicited_response(
            objects=tuple(objects),
            iin=self.iin,
            seq=seq,
            con=True,  # IEEE 1815-2012 4.2.2.4.3 Rule 3: unsolicited responses always request CON.
        )

    def clear_restart(self) -> None:
        """Clear the DEVICE_RESTART IIN flag.

        Call this after completing startup initialization.
        """
        self._state.clear_restart()
