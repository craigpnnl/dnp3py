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

# A block's data length function from its object header, or why it has none.
_LengthLookup = Callable[[ObjectHeader], _DataLength | TruncationReason]

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

# 4.2.2.7.3.1: qualifier bit 7 is reserved and must be clear.
_RESERVED_BIT = 0x80

# Table 4-6: an index prefix (codes 1 to 3) is defined with any count range
# (7 to 9), whatever its own width (0x17-0x19, 0x27-0x29, 0x37-0x39). Keyed on
# the raw 3-bit prefix and 4-bit range fields so they can be checked before
# the qualifier is known decodable.
_INDEX_PREFIX_CODES_RAW = frozenset(
    {PrefixCode.UINT8_INDEX.value, PrefixCode.UINT16_INDEX.value, PrefixCode.UINT32_INDEX.value}
)
_INDEX_PREFIX_VALID_RANGES = frozenset(
    {RangeCode.UINT8_COUNT.value, RangeCode.UINT16_COUNT.value, RangeCode.UINT32_COUNT.value}
)

# Table 4-6: the free-format range (0xB) is defined only with a size prefix
# (0x4B, 0x5B, 0x6B). Any other prefix paired with it is a shaded, undefined cell.
_FREE_FORMAT_RANGE_CODE = RangeCode.FREE_FORMAT.value
_SIZE_PREFIX_CODES_RAW = frozenset(
    {PrefixCode.UINT8_SIZE.value, PrefixCode.UINT16_SIZE.value, PrefixCode.UINT32_SIZE.value}
)

# A.1: group 0 variations without a per-object TLV (variation 0, general rule
# 4.2.2.7.2.1: variation 0 is request-only; variation 254, A.1.43.2: "does not
# have objects"). Both fall through to the ordinary lookup, which finds no
# layout or registry row and stops at UNKNOWN_WIDTH.
_GROUP_0_NO_OBJECT_VARIATIONS = frozenset({0, 254})

# A.1.1.2.2 (and every other A.1 variation): attribute data type code (1
# octet) plus length (1 octet), ahead of each object's value.
_ATTRIBUTE_TYPE_LENGTH_SIZE = 2

# Table 5-16 (5.5.4.3): attribute data type code 255 (U8BS8EXLIST) is the one
# code whose true length is not its length octet alone: the object's length
# is 256 plus the length octet's value, so a list past 255 octets can still
# be declared.
_EXTENDED_LIST_TYPE_CODE = 255
_EXTENDED_LIST_LENGTH_OFFSET = 256


# Request functions whose object headers carry no object data (IEEE 1815-2012 4.4): a
# block is its header, its range field and any index list. Every other request is
# framed by object width, as a response is.
_HEADER_ONLY_FUNCTIONS = frozenset(
    {
        FunctionCode.CONFIRM,
        FunctionCode.READ,
        FunctionCode.IMMEDIATE_FREEZE,
        FunctionCode.IMMEDIATE_FREEZE_NO_ACK,
        FunctionCode.FREEZE_CLEAR,
        FunctionCode.FREEZE_CLEAR_NO_ACK,
        FunctionCode.COLD_RESTART,
        FunctionCode.WARM_RESTART,
        FunctionCode.ENABLE_UNSOLICITED,
        FunctionCode.DISABLE_UNSOLICITED,
        FunctionCode.ASSIGN_CLASS,
        FunctionCode.DELAY_MEASURE,
        FunctionCode.RECORD_CURRENT_TIME,
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
        RangeCode.FREE_FORMAT: CountRange.from_bytes_1,  # Table 4-5 row B: 1-octet count.
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
    count_codes = {
        RangeCode.UINT8_COUNT,
        RangeCode.UINT16_COUNT,
        RangeCode.UINT32_COUNT,
        RangeCode.FREE_FORMAT,
    }
    if range_code in count_codes:
        return _parse_count_range(data, range_code, required)

    # Reserved or unsupported range codes
    return ParsedRange(start=0, stop=0, count=0, bytes_consumed=0)


def _index_list_length(count: int, prefix_width: int) -> int:
    # A start-stop range below its start is left to the function's handler to judge.
    return prefix_width * max(count, 0)


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
    start_stop_may_name_no_object: bool = False,
) -> tuple[ObjectBlock, int]:
    """Parse a single object block from data.

    Args:
        data: Raw bytes starting at object header.
        object_size: Size of each object in bytes, if known. Ignored when
            ``length_of`` is given.
        length_of: Object data length for (count, index prefix width), if known.
            If neither is known, a block carrying objects takes all remaining data.
        start_stop_may_name_no_object: Accept a start-stop range whose stop is
            below its start, for a block that carries no object data.

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
    if (
        length_of is not None
        and not start_stop_may_name_no_object
        and header.range_code in _START_STOP_CODES
        and parsed_range.count < 1
    ):
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


def _walk_free_format_block(data: bytes, header: ObjectHeader) -> tuple[ObjectBlock, int]:
    """Frame one size-prefixed free-format block (qualifier 0x4B, 0x5B or 0x6B).

    Table 4-6: this is the only pairing valid with the free-format range. The
    range field is a 1-octet object count (Table 4-5 row B); each object then
    carries its own size field ahead of its data, since the group's wire
    format has no fixed or registry width to look up. Objects are walked to
    locate the next header, not decoded: their bytes are kept as-is in the
    block's data.

    Args:
        data: Raw bytes starting at the object header.
        header: The already-parsed header for `data`.

    Returns:
        Tuple of (ObjectBlock, bytes_consumed).

    Raises:
        ParseError: If the count field, an object's size field, or its
            declared payload runs past the end of the data.
    """
    consumed = OBJECT_HEADER_SIZE
    parsed_range = _parse_range(data[consumed:], header.range_code)
    consumed += parsed_range.bytes_consumed
    prefix_size = get_prefix_size(header.prefix_code)

    for _ in range(parsed_range.count):
        remaining = data[consumed:]
        if len(remaining) < prefix_size:
            msg = f"Object size field requires {prefix_size} bytes, got {len(remaining)}"
            raise ParseError(msg)
        object_size = int.from_bytes(remaining[:prefix_size], byteorder="little")
        consumed += prefix_size
        remaining = data[consumed:]
        if len(remaining) < object_size:
            msg = f"Object data requires {object_size} bytes, got {len(remaining)}"
            raise ParseError(msg)
        consumed += object_size

    return ObjectBlock(header=header, data=data[OBJECT_HEADER_SIZE:consumed]), consumed


def _walk_group0_block(data: bytes, header: ObjectHeader) -> tuple[ObjectBlock, int]:
    """Frame one group 0 device-attribute block by its per-object TLV width.

    A.1.1.2.2 (and every other A.1 variation): each attribute value is a
    UINT8 attribute data type code, a UINT8 length, then `length` octets of
    value. Width per object is 2 + length; objects are walked to locate the
    next header, not decoded. An index prefix (qualifier 0x17, EX 5-11) sits
    ahead of each object's type/length pair; a start-stop range (qualifier
    0x00, EX 5-10) has none.

    Args:
        data: Raw bytes starting at the object header.
        header: The already-parsed header for `data`.

    Returns:
        Tuple of (ObjectBlock, bytes_consumed).

    Raises:
        ParseError: If the range field, an object's type/length window, or its
            declared value runs past the end of the data.
        _RangeNamesNoObject: If a start-stop range's stop index is below its
            start index: this path never frames a header-only block, so a
            stop below start names no object here (4.2.2.7.3.3).
    """
    consumed = OBJECT_HEADER_SIZE
    parsed_range = _parse_range(data[consumed:], header.range_code)
    consumed += parsed_range.bytes_consumed
    if header.range_code in _START_STOP_CODES and parsed_range.count < 1:
        msg = f"Start-stop range {parsed_range.start}..{parsed_range.stop} names no object"
        raise _RangeNamesNoObject(msg)
    prefix_size = get_prefix_size(header.prefix_code)

    for _ in range(parsed_range.count):
        remaining = data[consumed:]
        if len(remaining) < prefix_size:
            msg = f"Object index prefix requires {prefix_size} bytes, got {len(remaining)}"
            raise ParseError(msg)
        consumed += prefix_size
        remaining = data[consumed:]
        if len(remaining) < _ATTRIBUTE_TYPE_LENGTH_SIZE:
            msg = f"Attribute type/length window requires {_ATTRIBUTE_TYPE_LENGTH_SIZE} bytes, got {len(remaining)}"
            raise ParseError(msg)
        type_code = remaining[0]
        value_length = remaining[1]
        if type_code == _EXTENDED_LIST_TYPE_CODE:
            value_length += _EXTENDED_LIST_LENGTH_OFFSET
        consumed += _ATTRIBUTE_TYPE_LENGTH_SIZE
        remaining = data[consumed:]
        if len(remaining) < value_length:
            msg = f"Attribute value requires {value_length} bytes, got {len(remaining)}"
            raise ParseError(msg)
        consumed += value_length

    return ObjectBlock(header=header, data=data[OBJECT_HEADER_SIZE:consumed]), consumed


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
    """Parse object headers that carry no object data.

    Each block is its header, its range field and any index list, as in a READ.
    The blocks of the header-only form of `frame_request_object_blocks`, without
    the reason framing stopped.

    Args:
        data: Raw bytes containing object headers.

    Returns:
        List of ObjectBlocks with header, range and index data only.
    """
    blocks, _truncation = _frame_object_blocks(data, _lookup_index_list_length, start_stop_may_name_no_object=True)
    return blocks


def _unsupported_qualifier(header: ObjectHeader) -> TruncationReason | None:
    """Why a qualifier gives no length whatever the object, or None.

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
    return None


def _lookup_index_list_length(header: ObjectHeader) -> _DataLength | TruncationReason:
    """Length function for a block with no object data: one index prefix per object."""
    return _unsupported_qualifier(header) or _index_list_length


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
    unsupported = _unsupported_qualifier(header)
    if unsupported is not None:
        return unsupported
    layout = layout_for(header.group, header.variation)
    if layout is not None:
        return partial(data_length, layout)
    size = registry.get_size(header.group, header.variation)
    if size is None or size < 0:
        # A negative registered size would move the next header backwards.
        return TruncationReason.UNKNOWN_WIDTH
    return partial(_fixed_width_length, size)


def _has_reserved_code(qualifier: int) -> bool:
    """Whether the qualifier octet is not one IEEE 1815-2012 defines.

    Covers the reserved bit (4.2.2.7.3.1), prefix code 7 and range codes 0xA
    and 0xC to 0xF (Tables 4-4, 4-5); an index prefix paired with any range
    but a count range; and the free-format range (0xB) paired with any
    prefix but a size prefix (Table 4-6). A size prefix's own Table 4-6
    range rule is instead a length-lookup result (`_unsupported_qualifier`),
    since a size prefix can lack a usable width for other reasons too.
    """
    prefix = (qualifier >> 4) & 0x07
    range_code = qualifier & 0x0F
    return bool(
        qualifier & _RESERVED_BIT
        or prefix == _RESERVED_PREFIX_CODE
        or range_code in _RESERVED_RANGE_CODES
        or (prefix in _INDEX_PREFIX_CODES_RAW and range_code not in _INDEX_PREFIX_VALID_RANGES)
        or (range_code == _FREE_FORMAT_RANGE_CODE and prefix not in _SIZE_PREFIX_CODES_RAW)
    )


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

    A response carries values, so each block is delimited by its own object
    width for the next block's header to be found.

    An object header carries no length (IEEE 1815-2012 4.2.2.7), so a block
    whose length cannot be determined, or whose declared data runs past the
    end, leaves every later boundary unknown. Framing stops at that block: the
    blocks before it are returned, the block itself is not, and the returned
    `Truncation` names it. Its bytes are never attached to another header.

    Returns:
        The framed blocks, and the truncation, or None if every octet was framed.
    """
    return _frame_object_blocks(data, _lookup_data_length)


def frame_request_object_blocks(function: FunctionCode, data: bytes) -> tuple[list[ObjectBlock], Truncation | None]:
    """Split a request's object data into blocks, and say why framing stopped early.

    A function whose requests carry no object data (READ, the freezes, the
    restarts, ENABLE and DISABLE_UNSOLICITED and others, IEEE 1815-2012 4.4)
    frames each block as its header, range field and any index list. Every
    other function frames each block by object width, as a response is framed.
    Framing stops as `frame_response_object_blocks` describes.

    Returns:
        The framed blocks, and the truncation, or None if every octet was framed.
    """
    if function in _HEADER_ONLY_FUNCTIONS:
        return _frame_object_blocks(data, _lookup_index_list_length, start_stop_may_name_no_object=True)
    return _frame_object_blocks(data, _lookup_data_length)


def _frame_object_blocks(
    data: bytes,
    lookup: _LengthLookup,
    *,
    start_stop_may_name_no_object: bool = False,
) -> tuple[list[ObjectBlock], Truncation | None]:
    blocks: list[ObjectBlock] = []
    offset = 0

    while offset < len(data):
        remaining = data[offset:]
        if len(remaining) < OBJECT_HEADER_SIZE:
            return blocks, Truncation(reason=TruncationReason.TRAILING_OCTETS, offset=offset)

        header = ObjectHeader.from_bytes(remaining)
        if _has_reserved_code(header.qualifier):
            return blocks, _stopped_at(TruncationReason.RESERVED_QUALIFIER, offset, header)

        if header.range_code == RangeCode.FREE_FORMAT and header.prefix_code.value in _SIZE_PREFIX_CODES_RAW:
            # Table 4-6's one valid free-format pairing: each object sizes
            # itself, ahead of both length-lookup functions below.
            try:
                block, block_consumed = _walk_free_format_block(remaining, header)
            except ParseError:
                return blocks, _stopped_at(TruncationReason.DATA_SHORTER_THAN_DECLARED, offset, header)
            blocks.append(block)
            offset += block_consumed
            continue

        if (
            header.group == 0
            and header.variation not in _GROUP_0_NO_OBJECT_VARIATIONS
            and lookup is _lookup_data_length
        ):
            # Table 12-1: READ carries no group 0 attribute data (function
            # code 1, qualifier 00/06 only). Every request `_HEADER_ONLY_FUNCTIONS`
            # does not name (WRITE, SELECT, OPERATE, and the rest) and every
            # RESPONSE (129) do. `lookup is _lookup_data_length` is exactly
            # that split: a header-only request never reaches here.
            unsupported = _unsupported_qualifier(header)
            if unsupported is not None:
                return blocks, _stopped_at(unsupported, offset, header)
            try:
                block, block_consumed = _walk_group0_block(remaining, header)
            except ParseError:
                return blocks, _stopped_at(TruncationReason.DATA_SHORTER_THAN_DECLARED, offset, header)
            except _RangeNamesNoObject:
                return blocks, _stopped_at(TruncationReason.RANGE_NAMES_NO_OBJECT, offset, header)
            blocks.append(block)
            offset += block_consumed
            continue

        length_or_reason = lookup(header)

        length_of: _DataLength | None = None
        if not isinstance(length_or_reason, TruncationReason):
            length_of = length_or_reason
        elif header.range_code != RangeCode.ALL_OBJECTS or length_or_reason != TruncationReason.UNKNOWN_WIDTH:
            return blocks, _stopped_at(length_or_reason, offset, header)
        # Otherwise an all-objects block whose only problem is an unknown width
        # has no range field and no objects, so it frames as its header alone.
        # A prefix Table 4-6 does not allow with an all-objects range
        # (SIZE_PREFIX) stops above instead: it names no object to size, so
        # "unknown width" never applies to it.

        try:
            block, consumed = _parse_object_block(
                remaining, length_of=length_of, start_stop_may_name_no_object=start_stop_may_name_no_object
            )
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

    Every object block is framed on its own (`frame_request_object_blocks`).
    A block that cannot be framed, and every block after it, is absent from
    ``objects`` and named by ``truncation``.

    Args:
        data: Raw request bytes.

    Returns:
        Parsed RequestFragment.

    Raises:
        ParseError: If the request header cannot be parsed.
    """
    header, consumed = parse_request_header(data)
    remaining = data[consumed:]

    objects, truncation = frame_request_object_blocks(header.function, remaining)

    return RequestFragment(header=header, objects=tuple(objects), truncation=truncation)


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
