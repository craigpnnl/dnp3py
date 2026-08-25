"""Application layer parser per IEEE 1815-2012.

Parses raw bytes into application layer structures (requests, responses, objects).
"""

from dataclasses import dataclass

from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
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

# Prefix codes that prefix each object with its index. The size prefixes
# (UINT8_SIZE and up) describe variable-format objects, whose width the registry
# cannot supply.
_INDEX_PREFIX_CODES = frozenset(
    {
        PrefixCode.NONE,
        PrefixCode.UINT8_INDEX,
        PrefixCode.UINT16_INDEX,
        PrefixCode.UINT32_INDEX,
    }
)

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
    start_stop_codes = {
        RangeCode.UINT8_START_STOP,
        RangeCode.UINT16_START_STOP,
        RangeCode.UINT32_START_STOP,
    }
    if range_code in start_stop_codes:
        return _parse_start_stop_range(data, range_code, required)

    # Count ranges
    count_codes = {RangeCode.UINT8_COUNT, RangeCode.UINT16_COUNT, RangeCode.UINT32_COUNT}
    if range_code in count_codes:
        return _parse_count_range(data, range_code, required)

    # Reserved or unsupported range codes
    return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)


def _parse_object_block(
    data: bytes,
    object_size: int | None = None,
) -> tuple[ObjectBlock, int]:
    """Parse a single object block from data.

    Args:
        data: Raw bytes starting at object header.
        object_size: Size of each object in bytes, if known. If None, parses header only.

    Returns:
        Tuple of (ObjectBlock, bytes_consumed).

    Raises:
        ParseError: If data is too short.
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

    # If count is 0, just return range data
    if parsed_range.count == 0:
        range_data = data[OBJECT_HEADER_SIZE:consumed]
        return ObjectBlock(header=header, data=range_data), consumed

    # If we don't know object size, include all remaining data after the header
    # This works for single-block requests (common for control operations)
    if object_size is None:
        all_data = data[OBJECT_HEADER_SIZE:]
        return ObjectBlock(header=header, data=all_data), len(data)

    # Calculate total data size
    prefix_size = get_prefix_size(header.prefix_code)
    total_object_size = (prefix_size + object_size) * parsed_range.count

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


def _lookup_object_size(header: ObjectHeader) -> int | None:
    """Per-object size in bytes for a block's group/variation, or None.

    The object width comes from the object registry, which knows every
    registered group/variation including timestamped event variations (g2v2 is
    7 bytes, g32v3 is 11) and float variations (g30v5 is 5, g30v6 is 9). Reading
    it from the registry keeps one source of truth for object widths instead of
    a second table in the parser.

    Returns None for group/variations the registry does not know: g1v1 packed
    format is bit-packed rather than fixed per-object, and groups 40/42 are not
    registered. Callers then fall back to consuming the rest of the fragment,
    which is the historical behaviour and correct when the block is last.

    Raises:
        ValueError: If the qualifier holds a reserved range or prefix code. Both
            are enum lookups, so decoding them here means a reserved qualifier
            fails in this call, where the caller guards for it, rather than
            surfacing mid-block-parse.
    """
    # Decoded (not just validated) so a reserved qualifier raises here, and so
    # the sizes below are keyed off codes this function has actually resolved.
    range_code = header.range_code
    prefix_code = header.prefix_code
    if get_range_size(range_code) == 0 and range_code != RangeCode.ALL_OBJECTS:
        return None  # Unsupported range specifier: width is unknowable.
    if get_prefix_size(prefix_code) and prefix_code not in _INDEX_PREFIX_CODES:
        return None  # Size prefixes describe variable-format objects.
    return registry.get_size(header.group, header.variation)


def parse_response_object_blocks(data: bytes) -> list[ObjectBlock]:
    """Parse response object blocks, bounding each by its object data size.

    Distinct from `parse_object_headers`, which is for *requests*: a request
    (READ, for instance) carries object headers and range specifiers but no
    object data, so consuming a per-object width there would over-read. A
    response carries values, so each block must be delimited by its own size
    for the next block's header to be found.

    A block whose size cannot be determined absorbs the remaining fragment, so
    an unknown group/variation costs the blocks after it rather than corrupting
    the ones before it.

    When a block declares more objects than its data holds, the block is still
    returned carrying the bytes that are present, but parsing stops there: the
    declared width is the only thing that locates the next header, so once the
    data contradicts it any following boundary is a guess. Truncated trailing
    data therefore costs the blocks after it, never the ones before.
    """
    blocks: list[ObjectBlock] = []
    offset = 0

    while offset < len(data):
        remaining = data[offset:]
        if len(remaining) < OBJECT_HEADER_SIZE:
            break  # Not enough for another header

        try:
            header = ObjectHeader.from_bytes(remaining)
            object_size = _lookup_object_size(header)
        except ValueError:
            # A reserved qualifier has no decodable range or prefix code, so the
            # block's width is unknowable. Stop here and keep what came before
            # rather than letting it propagate and discard the whole response.
            break

        if object_size is None and header.range_code != RangeCode.ALL_OBJECTS:
            # Width unknown for a block that does carry objects. Take the rest of
            # the fragment: guessing a boundary would decode the payload of this
            # block as the header of the next one.
            blocks.append(ObjectBlock(header=header, data=remaining[OBJECT_HEADER_SIZE:]))
            break

        try:
            block, consumed = _parse_object_block(remaining, object_size=object_size)
        except (ParseError, ValueError):
            # Declared object count exceeds the bytes available. Keep the block
            # with the data present, then stop: the next boundary is unknowable.
            blocks.append(ObjectBlock(header=header, data=remaining[OBJECT_HEADER_SIZE:]))
            break

        blocks.append(block)
        if consumed <= 0:  # pragma: no cover - defensive
            # Unreachable: _parse_object_block always consumes the 3-byte header.
            # Kept so a future change to its return contract cannot spin here.
            break
        offset += consumed

    return blocks


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
    objects = parse_response_object_blocks(remaining)

    return ResponseFragment(header=header, objects=tuple(objects))


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
