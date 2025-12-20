"""Application layer builder for constructing requests and responses.

Factory functions for building common DNP3 application layer messages.
"""

from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader, ResponseHeader
from dnp3.application.qualifiers import (
    CountRange,
    ObjectHeader,
    PrefixCode,
    RangeCode,
    StartStopRange,
)
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN

# Size limits for range specifier selection
MAX_UINT8 = 255
MAX_UINT16 = 65535

# Class data group/variations (Group 60)
CLASS_0_GV = (60, 1)
CLASS_1_GV = (60, 2)
CLASS_2_GV = (60, 3)
CLASS_3_GV = (60, 4)


def build_read_request(
    objects: tuple[ObjectBlock, ...],
    seq: int = 0,
    fir: bool = True,
    fin: bool = True,
) -> RequestFragment:
    """Build a READ request.

    Args:
        objects: Object blocks to read.
        seq: Sequence number.
        fir: First fragment flag.
        fin: Final fragment flag.

    Returns:
        RequestFragment for READ.
    """
    header = RequestHeader.build(function=FunctionCode.READ, seq=seq, fir=fir, fin=fin)
    return RequestFragment(header=header, objects=objects)


def build_write_request(
    objects: tuple[ObjectBlock, ...],
    seq: int = 0,
    fir: bool = True,
    fin: bool = True,
) -> RequestFragment:
    """Build a WRITE request.

    Args:
        objects: Object blocks to write.
        seq: Sequence number.
        fir: First fragment flag.
        fin: Final fragment flag.

    Returns:
        RequestFragment for WRITE.
    """
    header = RequestHeader.build(function=FunctionCode.WRITE, seq=seq, fir=fir, fin=fin)
    return RequestFragment(header=header, objects=objects)


def build_integrity_poll(seq: int = 0) -> RequestFragment:
    """Build an integrity poll (READ class 0, 1, 2, 3).

    Args:
        seq: Sequence number.

    Returns:
        RequestFragment for integrity poll.
    """
    blocks = []
    for group, variation in [CLASS_1_GV, CLASS_2_GV, CLASS_3_GV, CLASS_0_GV]:
        header = ObjectHeader.build(
            group=group,
            variation=variation,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))

    return build_read_request(objects=tuple(blocks), seq=seq)


def build_class_poll(
    class_1: bool = True,
    class_2: bool = True,
    class_3: bool = True,
    seq: int = 0,
) -> RequestFragment:
    """Build an event class poll.

    Args:
        class_1: Include Class 1 events.
        class_2: Include Class 2 events.
        class_3: Include Class 3 events.
        seq: Sequence number.

    Returns:
        RequestFragment for event poll.
    """
    blocks = []
    if class_1:
        header = ObjectHeader.build(
            group=CLASS_1_GV[0],
            variation=CLASS_1_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_2:
        header = ObjectHeader.build(
            group=CLASS_2_GV[0],
            variation=CLASS_2_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_3:
        header = ObjectHeader.build(
            group=CLASS_3_GV[0],
            variation=CLASS_3_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))

    return build_read_request(objects=tuple(blocks), seq=seq)


def build_all_objects_request(
    function: FunctionCode,
    group: int,
    variation: int,
    seq: int = 0,
) -> RequestFragment:
    """Build a request for all objects of a type.

    Args:
        function: Function code (e.g., READ, WRITE).
        group: Object group number.
        variation: Object variation number.
        seq: Sequence number.

    Returns:
        RequestFragment.
    """
    obj_header = ObjectHeader.build(
        group=group,
        variation=variation,
        prefix=PrefixCode.NONE,
        range_code=RangeCode.ALL_OBJECTS,
    )
    block = ObjectBlock(header=obj_header)
    header = RequestHeader.build(function=function, seq=seq)
    return RequestFragment(header=header, objects=(block,))


def build_range_request(
    function: FunctionCode,
    group: int,
    variation: int,
    start: int,
    stop: int,
    seq: int = 0,
) -> RequestFragment:
    """Build a request for a range of objects.

    Args:
        function: Function code (e.g., READ, WRITE).
        group: Object group number.
        variation: Object variation number.
        start: Start index.
        stop: Stop index (inclusive).
        seq: Sequence number.

    Returns:
        RequestFragment.
    """
    # Choose appropriate range code based on values
    if start <= MAX_UINT8 and stop <= MAX_UINT8:
        range_code = RangeCode.UINT8_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_1()
    elif start <= MAX_UINT16 and stop <= MAX_UINT16:
        range_code = RangeCode.UINT16_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_2()
    else:
        range_code = RangeCode.UINT32_START_STOP
        range_data = StartStopRange(start=start, stop=stop).to_bytes_4()

    obj_header = ObjectHeader.build(
        group=group,
        variation=variation,
        prefix=PrefixCode.NONE,
        range_code=range_code,
    )
    block = ObjectBlock(header=obj_header, data=range_data)
    header = RequestHeader.build(function=function, seq=seq)
    return RequestFragment(header=header, objects=(block,))


def build_count_request(
    function: FunctionCode,
    group: int,
    variation: int,
    count: int,
    seq: int = 0,
) -> RequestFragment:
    """Build a request for a count of objects.

    Args:
        function: Function code (e.g., READ).
        group: Object group number.
        variation: Object variation number.
        count: Number of objects.
        seq: Sequence number.

    Returns:
        RequestFragment.
    """
    # Choose appropriate range code based on count
    if count <= MAX_UINT8:
        range_code = RangeCode.UINT8_COUNT
        range_data = CountRange(count=count).to_bytes_1()
    elif count <= MAX_UINT16:
        range_code = RangeCode.UINT16_COUNT
        range_data = CountRange(count=count).to_bytes_2()
    else:
        range_code = RangeCode.UINT32_COUNT
        range_data = CountRange(count=count).to_bytes_4()

    obj_header = ObjectHeader.build(
        group=group,
        variation=variation,
        prefix=PrefixCode.NONE,
        range_code=range_code,
    )
    block = ObjectBlock(header=obj_header, data=range_data)
    header = RequestHeader.build(function=function, seq=seq)
    return RequestFragment(header=header, objects=(block,))


def build_null_response(
    iin: IIN | None = None,
    seq: int = 0,
    fir: bool = True,
    fin: bool = True,
) -> ResponseFragment:
    """Build a null (empty) response.

    Args:
        iin: Internal indications.
        seq: Sequence number.
        fir: First fragment flag.
        fin: Final fragment flag.

    Returns:
        ResponseFragment with no objects.
    """
    header = ResponseHeader.build(
        function=FunctionCode.RESPONSE,
        iin=iin,
        seq=seq,
        fir=fir,
        fin=fin,
    )
    return ResponseFragment(header=header)


def build_response(
    objects: tuple[ObjectBlock, ...],
    iin: IIN | None = None,
    seq: int = 0,
    fir: bool = True,
    fin: bool = True,
) -> ResponseFragment:
    """Build a response with objects.

    Args:
        objects: Object blocks to include.
        iin: Internal indications.
        seq: Sequence number.
        fir: First fragment flag.
        fin: Final fragment flag.

    Returns:
        ResponseFragment.
    """
    header = ResponseHeader.build(
        function=FunctionCode.RESPONSE,
        iin=iin,
        seq=seq,
        fir=fir,
        fin=fin,
    )
    return ResponseFragment(header=header, objects=objects)


def build_unsolicited_response(
    objects: tuple[ObjectBlock, ...],
    iin: IIN | None = None,
    seq: int = 0,
    fir: bool = True,
    fin: bool = True,
) -> ResponseFragment:
    """Build an unsolicited response.

    Args:
        objects: Object blocks to include.
        iin: Internal indications.
        seq: Sequence number.
        fir: First fragment flag.
        fin: Final fragment flag.

    Returns:
        ResponseFragment with UNS flag set.
    """
    header = ResponseHeader.build(
        function=FunctionCode.UNSOLICITED_RESPONSE,
        iin=iin,
        seq=seq,
        fir=fir,
        fin=fin,
        uns=True,
    )
    return ResponseFragment(header=header, objects=objects)


def build_confirm_request(seq: int) -> RequestFragment:
    """Build a CONFIRM request.

    Args:
        seq: Sequence number to confirm.

    Returns:
        RequestFragment for CONFIRM.
    """
    header = RequestHeader.build(function=FunctionCode.CONFIRM, seq=seq)
    return RequestFragment(header=header)


def build_direct_operate_request(
    objects: tuple[ObjectBlock, ...],
    seq: int = 0,
) -> RequestFragment:
    """Build a DIRECT_OPERATE request.

    Args:
        objects: Control objects to operate.
        seq: Sequence number.

    Returns:
        RequestFragment for DIRECT_OPERATE.
    """
    header = RequestHeader.build(function=FunctionCode.DIRECT_OPERATE, seq=seq)
    return RequestFragment(header=header, objects=objects)


def build_select_request(
    objects: tuple[ObjectBlock, ...],
    seq: int = 0,
) -> RequestFragment:
    """Build a SELECT request (first step of SBO).

    Args:
        objects: Control objects to select.
        seq: Sequence number.

    Returns:
        RequestFragment for SELECT.
    """
    header = RequestHeader.build(function=FunctionCode.SELECT, seq=seq)
    return RequestFragment(header=header, objects=objects)


def build_operate_request(
    objects: tuple[ObjectBlock, ...],
    seq: int = 0,
) -> RequestFragment:
    """Build an OPERATE request (second step of SBO).

    Args:
        objects: Control objects to operate.
        seq: Sequence number.

    Returns:
        RequestFragment for OPERATE.
    """
    header = RequestHeader.build(function=FunctionCode.OPERATE, seq=seq)
    return RequestFragment(header=header, objects=objects)


def build_delay_measure_request(seq: int = 0) -> RequestFragment:
    """Build a DELAY_MEASURE request for time sync.

    Args:
        seq: Sequence number.

    Returns:
        RequestFragment for DELAY_MEASURE.
    """
    header = RequestHeader.build(function=FunctionCode.DELAY_MEASURE, seq=seq)
    return RequestFragment(header=header)


def build_cold_restart_request(seq: int = 0) -> RequestFragment:
    """Build a COLD_RESTART request.

    Args:
        seq: Sequence number.

    Returns:
        RequestFragment for COLD_RESTART.
    """
    header = RequestHeader.build(function=FunctionCode.COLD_RESTART, seq=seq)
    return RequestFragment(header=header)


def build_warm_restart_request(seq: int = 0) -> RequestFragment:
    """Build a WARM_RESTART request.

    Args:
        seq: Sequence number.

    Returns:
        RequestFragment for WARM_RESTART.
    """
    header = RequestHeader.build(function=FunctionCode.WARM_RESTART, seq=seq)
    return RequestFragment(header=header)


def build_enable_unsolicited_request(
    class_1: bool = True,
    class_2: bool = True,
    class_3: bool = True,
    seq: int = 0,
) -> RequestFragment:
    """Build an ENABLE_UNSOLICITED request.

    Args:
        class_1: Enable Class 1 unsolicited.
        class_2: Enable Class 2 unsolicited.
        class_3: Enable Class 3 unsolicited.
        seq: Sequence number.

    Returns:
        RequestFragment for ENABLE_UNSOLICITED.
    """
    blocks = []
    if class_1:
        header = ObjectHeader.build(
            group=CLASS_1_GV[0],
            variation=CLASS_1_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_2:
        header = ObjectHeader.build(
            group=CLASS_2_GV[0],
            variation=CLASS_2_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_3:
        header = ObjectHeader.build(
            group=CLASS_3_GV[0],
            variation=CLASS_3_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))

    req_header = RequestHeader.build(function=FunctionCode.ENABLE_UNSOLICITED, seq=seq)
    return RequestFragment(header=req_header, objects=tuple(blocks))


def build_disable_unsolicited_request(
    class_1: bool = True,
    class_2: bool = True,
    class_3: bool = True,
    seq: int = 0,
) -> RequestFragment:
    """Build a DISABLE_UNSOLICITED request.

    Args:
        class_1: Disable Class 1 unsolicited.
        class_2: Disable Class 2 unsolicited.
        class_3: Disable Class 3 unsolicited.
        seq: Sequence number.

    Returns:
        RequestFragment for DISABLE_UNSOLICITED.
    """
    blocks = []
    if class_1:
        header = ObjectHeader.build(
            group=CLASS_1_GV[0],
            variation=CLASS_1_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_2:
        header = ObjectHeader.build(
            group=CLASS_2_GV[0],
            variation=CLASS_2_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))
    if class_3:
        header = ObjectHeader.build(
            group=CLASS_3_GV[0],
            variation=CLASS_3_GV[1],
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        blocks.append(ObjectBlock(header=header))

    req_header = RequestHeader.build(function=FunctionCode.DISABLE_UNSOLICITED, seq=seq)
    return RequestFragment(header=req_header, objects=tuple(blocks))
