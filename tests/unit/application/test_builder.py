"""Tests for application layer builder."""

from dnp3.application.builder import (
    CLASS_0_GV,
    CLASS_1_GV,
    CLASS_2_GV,
    CLASS_3_GV,
    build_all_objects_request,
    build_class_poll,
    build_cold_restart_request,
    build_confirm_request,
    build_count_request,
    build_delay_measure_request,
    build_direct_operate_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
    build_integrity_poll,
    build_null_response,
    build_operate_request,
    build_range_request,
    build_read_request,
    build_response,
    build_select_request,
    build_unsolicited_response,
    build_warm_restart_request,
    build_write_request,
)
from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader, PrefixCode, RangeCode
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN


class TestClassConstants:
    """Tests for class data group/variation constants."""

    def test_class_0_gv(self) -> None:
        """Class 0 is Group 60 Var 1."""
        assert CLASS_0_GV == (60, 1)

    def test_class_1_gv(self) -> None:
        """Class 1 is Group 60 Var 2."""
        assert CLASS_1_GV == (60, 2)

    def test_class_2_gv(self) -> None:
        """Class 2 is Group 60 Var 3."""
        assert CLASS_2_GV == (60, 3)

    def test_class_3_gv(self) -> None:
        """Class 3 is Group 60 Var 4."""
        assert CLASS_3_GV == (60, 4)


class TestBuildReadRequest:
    """Tests for build_read_request function."""

    def test_empty_read(self) -> None:
        """Build READ with no objects."""
        fragment = build_read_request(objects=())
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 0

    def test_read_with_objects(self) -> None:
        """Build READ with objects."""
        obj_header = ObjectHeader.build(group=1, variation=2, prefix=PrefixCode.NONE, range_code=RangeCode.ALL_OBJECTS)
        block = ObjectBlock(header=obj_header)
        fragment = build_read_request(objects=(block,))
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 1

    def test_read_with_sequence(self) -> None:
        """Build READ with sequence number."""
        fragment = build_read_request(objects=(), seq=7)
        assert fragment.sequence == 7

    def test_read_multi_fragment(self) -> None:
        """Build READ for multi-fragment."""
        fragment = build_read_request(objects=(), fir=True, fin=False)
        assert fragment.is_first is True
        assert fragment.is_final is False


class TestBuildWriteRequest:
    """Tests for build_write_request function."""

    def test_write_request(self) -> None:
        """Build WRITE request."""
        obj_header = ObjectHeader.build(group=80, variation=1)
        block = ObjectBlock(header=obj_header, data=b"\x01\x00")
        fragment = build_write_request(objects=(block,))
        assert fragment.header.function == FunctionCode.WRITE


class TestBuildIntegrityPoll:
    """Tests for build_integrity_poll function."""

    def test_integrity_poll_objects(self) -> None:
        """Integrity poll includes class 1, 2, 3, 0."""
        fragment = build_integrity_poll()
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 4

    def test_integrity_poll_order(self) -> None:
        """Integrity poll has correct order: 1, 2, 3, 0."""
        fragment = build_integrity_poll()
        # Class 1, 2, 3 first (events), then Class 0 (static)
        assert fragment.objects[0].header.group == 60
        assert fragment.objects[0].header.variation == 2  # Class 1
        assert fragment.objects[1].header.variation == 3  # Class 2
        assert fragment.objects[2].header.variation == 4  # Class 3
        assert fragment.objects[3].header.variation == 1  # Class 0

    def test_integrity_poll_sequence(self) -> None:
        """Integrity poll with sequence."""
        fragment = build_integrity_poll(seq=5)
        assert fragment.sequence == 5


class TestBuildClassPoll:
    """Tests for build_class_poll function."""

    def test_all_classes(self) -> None:
        """Poll all event classes."""
        fragment = build_class_poll()
        assert len(fragment.objects) == 3

    def test_class_1_only(self) -> None:
        """Poll Class 1 only."""
        fragment = build_class_poll(class_1=True, class_2=False, class_3=False)
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.variation == 2  # Class 1

    def test_class_2_3_only(self) -> None:
        """Poll Class 2 and 3 only."""
        fragment = build_class_poll(class_1=False, class_2=True, class_3=True)
        assert len(fragment.objects) == 2
        assert fragment.objects[0].header.variation == 3  # Class 2
        assert fragment.objects[1].header.variation == 4  # Class 3


class TestBuildAllObjectsRequest:
    """Tests for build_all_objects_request function."""

    def test_read_all_binary_inputs(self) -> None:
        """Read all binary inputs."""
        fragment = build_all_objects_request(function=FunctionCode.READ, group=1, variation=2)
        assert fragment.header.function == FunctionCode.READ
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.group == 1
        assert fragment.objects[0].header.variation == 2
        assert fragment.objects[0].header.range_code == RangeCode.ALL_OBJECTS


class TestBuildRangeRequest:
    """Tests for build_range_request function."""

    def test_1_byte_range(self) -> None:
        """Build request with 1-byte range."""
        fragment = build_range_request(function=FunctionCode.READ, group=1, variation=2, start=0, stop=10)
        assert fragment.objects[0].header.range_code == RangeCode.UINT8_START_STOP
        assert fragment.objects[0].data == b"\x00\x0a"

    def test_2_byte_range(self) -> None:
        """Build request with 2-byte range."""
        fragment = build_range_request(function=FunctionCode.READ, group=30, variation=1, start=0, stop=1000)
        assert fragment.objects[0].header.range_code == RangeCode.UINT16_START_STOP
        # 1000 = 0x03E8 -> little endian
        assert fragment.objects[0].data == b"\x00\x00\xe8\x03"

    def test_4_byte_range(self) -> None:
        """Build request with 4-byte range."""
        fragment = build_range_request(function=FunctionCode.READ, group=30, variation=1, start=0, stop=100000)
        assert fragment.objects[0].header.range_code == RangeCode.UINT32_START_STOP


class TestBuildCountRequest:
    """Tests for build_count_request function."""

    def test_1_byte_count(self) -> None:
        """Build request with 1-byte count."""
        fragment = build_count_request(function=FunctionCode.READ, group=2, variation=1, count=10)
        assert fragment.objects[0].header.range_code == RangeCode.UINT8_COUNT
        assert fragment.objects[0].data == b"\x0a"

    def test_2_byte_count(self) -> None:
        """Build request with 2-byte count."""
        fragment = build_count_request(function=FunctionCode.READ, group=2, variation=1, count=1000)
        assert fragment.objects[0].header.range_code == RangeCode.UINT16_COUNT

    def test_4_byte_count(self) -> None:
        """Build request with 4-byte count."""
        fragment = build_count_request(function=FunctionCode.READ, group=2, variation=1, count=100000)
        assert fragment.objects[0].header.range_code == RangeCode.UINT32_COUNT


class TestBuildNullResponse:
    """Tests for build_null_response function."""

    def test_null_response(self) -> None:
        """Build null response."""
        fragment = build_null_response()
        assert fragment.header.function == FunctionCode.RESPONSE
        assert len(fragment.objects) == 0
        assert fragment.header.iin == IIN(0)

    def test_null_response_with_iin(self) -> None:
        """Build null response with IIN."""
        fragment = build_null_response(iin=IIN.DEVICE_RESTART)
        assert fragment.header.iin & IIN.DEVICE_RESTART

    def test_null_response_with_sequence(self) -> None:
        """Build null response with sequence."""
        fragment = build_null_response(seq=3)
        assert fragment.sequence == 3


class TestBuildResponse:
    """Tests for build_response function."""

    def test_response_with_objects(self) -> None:
        """Build response with objects."""
        obj_header = ObjectHeader.build(group=1, variation=2)
        block = ObjectBlock(header=obj_header, data=b"\x81")
        fragment = build_response(objects=(block,))
        assert fragment.header.function == FunctionCode.RESPONSE
        assert len(fragment.objects) == 1


class TestBuildUnsolicitedResponse:
    """Tests for build_unsolicited_response function."""

    def test_unsolicited_response(self) -> None:
        """Build unsolicited response."""
        obj_header = ObjectHeader.build(group=2, variation=1)
        block = ObjectBlock(header=obj_header, data=b"\x81")
        fragment = build_unsolicited_response(objects=(block,))
        assert fragment.header.function == FunctionCode.UNSOLICITED_RESPONSE
        assert fragment.is_unsolicited is True


class TestBuildConfirmRequest:
    """Tests for build_confirm_request function."""

    def test_confirm_request(self) -> None:
        """Build CONFIRM request."""
        fragment = build_confirm_request(seq=5)
        assert fragment.header.function == FunctionCode.CONFIRM
        assert fragment.sequence == 5
        assert len(fragment.objects) == 0


class TestBuildDirectOperateRequest:
    """Tests for build_direct_operate_request function."""

    def test_direct_operate(self) -> None:
        """Build DIRECT_OPERATE request."""
        obj_header = ObjectHeader.build(group=12, variation=1)
        block = ObjectBlock(header=obj_header, data=b"\x01")
        fragment = build_direct_operate_request(objects=(block,))
        assert fragment.header.function == FunctionCode.DIRECT_OPERATE


class TestBuildSelectRequest:
    """Tests for build_select_request function."""

    def test_select_request(self) -> None:
        """Build SELECT request."""
        obj_header = ObjectHeader.build(group=12, variation=1)
        block = ObjectBlock(header=obj_header, data=b"\x01")
        fragment = build_select_request(objects=(block,))
        assert fragment.header.function == FunctionCode.SELECT


class TestBuildOperateRequest:
    """Tests for build_operate_request function."""

    def test_operate_request(self) -> None:
        """Build OPERATE request."""
        obj_header = ObjectHeader.build(group=12, variation=1)
        block = ObjectBlock(header=obj_header, data=b"\x01")
        fragment = build_operate_request(objects=(block,))
        assert fragment.header.function == FunctionCode.OPERATE


class TestBuildDelayMeasureRequest:
    """Tests for build_delay_measure_request function."""

    def test_delay_measure(self) -> None:
        """Build DELAY_MEASURE request."""
        fragment = build_delay_measure_request()
        assert fragment.header.function == FunctionCode.DELAY_MEASURE
        assert len(fragment.objects) == 0


class TestBuildRestartRequests:
    """Tests for restart request builders."""

    def test_cold_restart(self) -> None:
        """Build COLD_RESTART request."""
        fragment = build_cold_restart_request()
        assert fragment.header.function == FunctionCode.COLD_RESTART

    def test_warm_restart(self) -> None:
        """Build WARM_RESTART request."""
        fragment = build_warm_restart_request()
        assert fragment.header.function == FunctionCode.WARM_RESTART


class TestBuildUnsolicitedControl:
    """Tests for unsolicited enable/disable builders."""

    def test_enable_unsolicited_all(self) -> None:
        """Enable unsolicited for all classes."""
        fragment = build_enable_unsolicited_request()
        assert fragment.header.function == FunctionCode.ENABLE_UNSOLICITED
        assert len(fragment.objects) == 3

    def test_enable_unsolicited_class_1_only(self) -> None:
        """Enable unsolicited for Class 1 only."""
        fragment = build_enable_unsolicited_request(class_1=True, class_2=False, class_3=False)
        assert len(fragment.objects) == 1
        assert fragment.objects[0].header.variation == 2

    def test_disable_unsolicited_all(self) -> None:
        """Disable unsolicited for all classes."""
        fragment = build_disable_unsolicited_request()
        assert fragment.header.function == FunctionCode.DISABLE_UNSOLICITED
        assert len(fragment.objects) == 3

    def test_disable_unsolicited_class_2_3(self) -> None:
        """Disable unsolicited for Classes 2 and 3."""
        fragment = build_disable_unsolicited_request(class_1=False, class_2=True, class_3=True)
        assert len(fragment.objects) == 2
