"""Application layer parser per IEEE 1815-2012.

Parses raw bytes into application layer structures (requests, responses, objects).
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from dnp3.application.fragment import (
    ObjectBlock,
    RequestFragment,
    ResponseFragment,
    Truncation,
    TruncationReason,
)
from dnp3.application.header import (
    REQUEST_HEADER_SIZE,
    RESPONSE_HEADER_SIZE,
    RequestHeader,
    ResponseHeader,
)
from dnp3.application.qualifiers import (
    OBJECT_HEADER_SIZE,
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
    get_prefix_size,
    get_range_size,
)
from dnp3.core.enums import FunctionCode
from dnp3.objects import registry
from dnp3.objects.layout import data_length, layout_for

# Octets of object data for (object count, index prefix width), or None when the
# block's objects cannot be laid out with that prefix.
_DataLength = Callable[[int, int], int | None]

# Prefix codes that prefix each object with its index. The size prefixes
# (UINT8_SIZE and up) describe variable-format objects, whose width neither the
# layout table nor the registry can supply.
_INDEX_PREFIX_CODES = frozenset(
    {
        PrefixCode.NONE,
        PrefixCode.UINT8_INDEX,
        PrefixCode.UINT16_INDEX,
        PrefixCode.UINT32_INDEX,
    }
)

_START_STOP_CODES = frozenset({RangeCode.UINT8_START_STOP, RangeCode.UINT16_START_STOP, RangeCode.UINT32_START_STOP})

# IEEE 1815-2012 Tables 4-4 and 4-5 reserve prefix code 7 and range codes 0xA and 0xC to 0xF.
_RESERVED_PREFIX_CODE = 0x07
_RESERVED_RANGE_CODES = frozenset({0x0A, 0x0C, 0x0D, 0x0E, 0x0F})


# Response function codes (0x81-0x83)
RESPONSE_FUNCTION_CODES = frozenset(
    {
        FunctionCode.RESPONSE,
        FunctionCode.UNSOLICITED_RESPONSE,
        FunctionCode.AUTHENTICATE_RESPONSE,
    }
)


@dataclass(frozen=True, slots=True)
class ParsedRange:
    """Parsed range specifier.

    Attributes:
        start: Start index (for start-stop ranges) or 0.
        stop: Stop index (for start-stop ranges) or count - 1.
        count: Number of objects.
        bytes_consumed: Bytes consumed parsing the range.
    """

    start: int
    stop: int
    count: int
    bytes_consumed: int


class ParseError(Exception):
    """Error during parsing."""


class _RangeNamesNoObject(ValueError):
    """A sized block's start-stop range has its stop index below its start index."""


class _NoObjectLength(Exception):
    """A block's length function gives no length for its count and index prefix."""


def _parse_start_stop_range(data: bytes, range_code: RangeCode, required: int) -> ParsedRange:
    """Parse start-stop range specifier."""
    parsers = {
        RangeCode.UINT8_START_STOP: StartStopRange.from_bytes_1,
        RangeCode.UINT16_START_STOP: StartStopRange.from_bytes_2,
        RangeCode.UINT32_START_STOP: StartStopRange.from_bytes_4,
    }
    parser = parsers.get(range_code)
    if parser is None:
        return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)
    r = parser(data)
    return ParsedRange(start=r.start, stop=r.stop, count=r.count, bytes_consumed=required)


def _parse_count_range(data: bytes, range_code: RangeCode, required: int) -> ParsedRange:
    """Parse count range specifier."""
    parsers = {
        RangeCode.UINT8_COUNT: CountRange.from_bytes_1,
        RangeCode.UINT16_COUNT: CountRange.from_bytes_2,
        RangeCode.UINT32_COUNT: CountRange.from_bytes_4,
    }
    parser = parsers.get(range_code)
    if parser is None:
        return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)
    c = parser(data)
    return ParsedRange(start=0, stop=c.count - 1, count=c.count, bytes_consumed=required)


def _parse_range(data: bytes, range_code: RangeCode) -> ParsedRange:
    """Parse range specifier from data.

    Args:
        data: Raw bytes after object header.
        range_code: Range specifier code from qualifier.

    Returns:
        Parsed range information.

    Raises:
        ParseError: If data is too short.
    """
    required = get_range_size(range_code)
    if len(data) < required:
        msg = f"Range specifier requires {required} bytes, got {len(data)}"
        raise ParseError(msg)

    # ALL_OBJECTS: no range data
    if range_code == RangeCode.ALL_OBJECTS:
        return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)

    # Start-stop ranges
    if range_code in _START_STOP_CODES:
        return _parse_start_stop_range(data, range_code, required)

    # Count ranges
    count_codes = {RangeCode.UINT8_COUNT, RangeCode.UINT16_COUNT, RangeCode.UINT32_COUNT}
    if range_code in count_codes:
        return _parse_count_range(data, range_code, required)

    # Reserved or unsupported range codes
    return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)


def _fixed_width_length(width: int, count: int, prefix_width: int) -> int:
    # The octet-aligned case of dnp3.objects.layout.data_length, for registry-only objects.
    if width < 0 or count < 0 or prefix_width < 0:
        msg = f"width, count and prefix width must be non-negative, got {width}, {count} and {prefix_width}"
        raise ValueError(msg)
    return (prefix_width + width) * count


def _parse_object_block(
    data: bytes,
    object_size: int | None = None,
    *,
    length_of: _DataLength | None = None,
) -> tuple[ObjectBlock, int]:
    """Parse a single object block from data.

    Args:
        data: Raw bytes starting at object header.
        object_size: Size of each object in bytes, if known. Ignored when
            ``length_of`` is given.
        length_of: Object data length for (count, index prefix width), if known.
            If neither is known, a block carrying objects takes all remaining data.

    Returns:
        Tuple of (ObjectBlock, bytes_consumed).

    Raises:
        ParseError: If data is too short.
        ValueError: If a sized block's start-stop range names no object.
        _NoObjectLength: If ``length_of`` gives None for the block's count and prefix.
    """
    if len(data) < OBJECT_HEADER_SIZE:
        msg = f"Object header requires {OBJECT_HEADER_SIZE} bytes, got {len(data)}"
        raise ParseError(msg)

    header = ObjectHeader.from_bytes(data)
    consumed = OBJECT_HEADER_SIZE
    remaining = data[consumed:]

    # Parse range specifier
    parsed_range = _parse_range(remaining, header.range_code)
    consumed += parsed_range.bytes_consumed
    remaining = data[consumed:]

    if length_of is None and object_size is not None:
        length_of = partial(_fixed_width_length, object_size)
    if length_of is not None and header.range_code in _START_STOP_CODES and parsed_range.count < 1:
        # IEEE 1815-2012 4.2.2.7.3.3: a start-stop range holds the start index through the stop
        # index, so a stop below the start is malformed and gives no length to find the next header.
        msg = f"Start-stop range {parsed_range.start}..{parsed_range.stop} names no object"
        raise _RangeNamesNoObject(msg)
    total_object_size = None
    if length_of is not None:
        total_object_size = length_of(parsed_range.count, get_prefix_size(header.prefix_code))
        if total_object_size is None:
            msg = f"No object data length for g{header.group}v{header.variation} qualifier 0x{header.qualifier:02X}"
            raise _NoObjectLength(msg)
    elif parsed_range.count == 0:
        range_data = data[OBJECT_HEADER_SIZE:consumed]
        return ObjectBlock(header=header, data=range_data), consumed

    # If we don't know the data length, include all remaining data after the header
    # This works for single-block requests (common for control operations)
    if total_object_size is None:
        all_data = data[OBJECT_HEADER_SIZE:]
        return ObjectBlock(header=header, data=all_data), len(data)

    if len(remaining) < total_object_size:
        msg = f"Object data requires {total_object_size} bytes, got {len(remaining)}"
        raise ParseError(msg)

    # Include range data + object data
    range_and_object_data = data[OBJECT_HEADER_SIZE : consumed + total_object_size]
    return ObjectBlock(header=header, data=range_and_object_data), consumed + total_object_size


def parse_request_header(data: bytes) -> tuple[RequestHeader, int]:
    """Parse request header from bytes.

    Args:
        data: Raw bytes starting at request header.

    Returns:
        Tuple of (RequestHeader, bytes_consumed).

    Raises:
        ParseError: If data is too short or invalid.
    """
    if len(data) < REQUEST_HEADER_SIZE:
        msg = f"Request header requires {REQUEST_HEADER_SIZE} bytes, got {len(data)}"
        raise ParseError(msg)

    try:
        header = RequestHeader.from_bytes(data)
    except ValueError as e:
        raise ParseError(str(e)) from e

    return header, REQUEST_HEADER_SIZE


def parse_response_header(data: bytes) -> tuple[ResponseHeader, int]:
    """Parse response header from bytes.

    Args:
        data: Raw bytes starting at response header.

    Returns:
        Tuple of (ResponseHeader, bytes_consumed).

    Raises:
        ParseError: If data is too short or invalid.
    """
    if len(data) < RESPONSE_HEADER_SIZE:
        msg = f"Response header requires {RESPONSE_HEADER_SIZE} bytes, got {len(data)}"
        raise ParseError(msg)

    try:
        header = ResponseHeader.from_bytes(data)
    except ValueError as e:
        raise ParseError(str(e)) from e

    return header, RESPONSE_HEADER_SIZE


def parse_object_headers(data: bytes) -> list[ObjectBlock]:
    """Parse object headers from data (header + range only, no object data).

    Used for parsing requests where we only need the headers.

    Args:
        data: Raw bytes containing object headers.

    Returns:
        List of ObjectBlocks with header and range data only.

    Raises:
        ParseError: If parsing fails.
    """
    blocks: list[ObjectBlock] = []
    offset = 0

    while offset < len(data):
        remaining = data[offset:]
        if len(remaining) < OBJECT_HEADER_SIZE:
            break  # Not enough for another header

        block, consumed = _parse_object_block(remaining, object_size=None)
        blocks.append(block)
        offset += consumed

    return blocks


def _lookup_data_length(header: ObjectHeader) -> _DataLength | TruncationReason:
    """Object data length function for a block's group/variation, or why there is none.

    The length comes from the wire-layout table, which also covers bit-packed
    variations (g1v1, g3v1, g10v1), whose length depends on the object count
    rather than a per-object width. A pair with no layout row falls back to the
    object registry, so an object registered by an application is bounded by
    its registered size and its index prefix.

    Raises:
        ValueError: If the qualifier holds a prefix code or range code that is
            not an enum member. Callers reject reserved codes first.
    """
    range_code = header.range_code
    prefix_code = header.prefix_code
    if get_range_size(range_code) == 0 and range_code != RangeCode.ALL_OBJECTS:
        return TruncationReason.UNSUPPORTED_RANGE
    if get_prefix_size(prefix_code) and prefix_code not in _INDEX_PREFIX_CODES:
        return TruncationReason.SIZE_PREFIX
    layout = layout_for(header.group, header.variation)
    if layout is not None:
        return partial(data_length, layout)
    size = registry.get_size(header.group, header.variation)
    if size is None or size < 0:
        # A negative registered size would move the next header backwards.
        return TruncationReason.UNKNOWN_WIDTH
    return partial(_fixed_width_length, size)


def _has_reserved_code(qualifier: int) -> bool:
    return (qualifier >> 4) & 0x07 == _RESERVED_PREFIX_CODE or qualifier & 0x0F in _RESERVED_RANGE_CODES


def parse_response_object_blocks(data: bytes) -> list[ObjectBlock]:
    """Parse response object blocks, bounding each by its object data size.

    The blocks of `frame_response_object_blocks`, without the reason parsing
    stopped.
    """
    blocks, _truncation = frame_response_object_blocks(data)
    return blocks


def _stopped_at(reason: TruncationReason, offset: int, header: ObjectHeader) -> Truncation:
    return Truncation(
        reason=reason,
        offset=offset,
        group=header.group,
        variation=header.variation,
        qualifier=header.qualifier,
    )


def frame_response_object_blocks(data: bytes) -> tuple[list[ObjectBlock], Truncation | None]:
    """Split a response's object data into blocks, and say why framing stopped early.

    Distinct from `parse_object_headers`, which is for *requests*: a request
    (READ, for instance) carries object headers and range specifiers but no
    object data, so consuming a per-object width there would over-read. A
    response carries values, so each block must be delimited by its own size
    for the next block's header to be found.

    An object header carries no length (IEEE 1815-2012 4.2.2.7), so a block
    whose length cannot be determined, or whose declared data runs past the
    end, leaves every later boundary unknown. Framing stops at that block: the
    blocks before it are returned, the block itself is not, and the returned
    `Truncation` names it. Its bytes are never attached to another header.

    Returns:
        The framed blocks, and the truncation, or None if every octet was framed.
    """
    blocks: list[ObjectBlock] = []
    offset = 0

    while offset < len(data):
        remaining = data[offset:]
        if len(remaining) < OBJECT_HEADER_SIZE:
            return blocks, Truncation(reason=TruncationReason.TRAILING_OCTETS, offset=offset)

        header = ObjectHeader.from_bytes(remaining)
        if _has_reserved_code(header.qualifier):
            return blocks, _stopped_at(TruncationReason.RESERVED_QUALIFIER, offset, header)
        sized = _lookup_data_length(header)

        length_of: _DataLength | None = None
        if not isinstance(sized, TruncationReason):
            length_of = sized
        elif header.range_code != RangeCode.ALL_OBJECTS:
            return blocks, _stopped_at(sized, offset, header)
        # Otherwise an all-objects block of unknown width: no range field and no
        # objects, so it frames as its header alone. One of known width goes
        # through its length, so a packed layout with an index prefix stops.

        try:
            block, consumed = _parse_object_block(remaining, length_of=length_of)
        except _RangeNamesNoObject:
            return blocks, _stopped_at(TruncationReason.RANGE_NAMES_NO_OBJECT, offset, header)
        except _NoObjectLength:
            return blocks, _stopped_at(TruncationReason.PACKED_WITH_INDEX_PREFIX, offset, header)
        except ParseError:
            return blocks, _stopped_at(TruncationReason.DATA_SHORTER_THAN_DECLARED, offset, header)

        if consumed <= 0:  # pragma: no cover - defensive
            # Unreachable while every length is non-negative, so a block consumes at
            # least its header. Kept so a change to that contract cannot spin here.
            return blocks, _stopped_at(TruncationReason.UNKNOWN_WIDTH, offset, header)
        blocks.append(block)
        offset += consumed

    return blocks, None


def parse_request(data: bytes) -> RequestFragment:
    """Parse a complete request fragment.

    Args:
        data: Raw request bytes.

    Returns:
        Parsed RequestFragment.

    Raises:
        ParseError: If parsing fails.
    """
    header, consumed = parse_request_header(data)
    remaining = data[consumed:]

    # Parse object headers (we don't know object sizes without group/variation lookup)
    objects = parse_object_headers(remaining)

    return RequestFragment(header=header, objects=tuple(objects))


def parse_response(data: bytes) -> ResponseFragment:
    """Parse a complete response fragment.

    Args:
        data: Raw response bytes.

    Returns:
        Parsed ResponseFragment.

    Raises:
        ParseError: If parsing fails.
    """
    header, consumed = parse_response_header(data)
    remaining = data[consumed:]

    # Size-aware: a response carries object data, so each block must be bounded
    # by its own width for the next block's header to be located.
    objects, truncation = frame_response_object_blocks(remaining)

    return ResponseFragment(header=header, objects=tuple(objects), truncation=truncation)


def is_request(data: bytes) -> bool:
    """Check if data starts with a request (not response).

    Args:
        data: Raw bytes starting at application control.

    Returns:
        True if this is a request, False if response.
    """
    if len(data) < REQUEST_HEADER_SIZE:
        return False

    function_code = data[1]
    return function_code not in {fc.value for fc in RESPONSE_FUNCTION_CODES}


def is_response(data: bytes) -> bool:
    """Check if data starts with a response.

    Args:
        data: Raw bytes starting at application control.

    Returns:
        True if this is a response, False otherwise.
    """
    if len(data) < REQUEST_HEADER_SIZE:
        return False

    function_code = data[1]
    return function_code in {fc.value for fc in RESPONSE_FUNCTION_CODES}
