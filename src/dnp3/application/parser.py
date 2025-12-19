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
    RangeCode,
    StartStopRange,
    get_prefix_size,
    get_range_size,
)
from dnp3.core.enums import FunctionCode

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

    # Parse object headers (we don't know object sizes without group/variation lookup)
    objects = parse_object_headers(remaining)

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
