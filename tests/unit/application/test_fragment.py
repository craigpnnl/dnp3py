"""Tests for application layer fragments."""

import pytest

from dnp3.application.fragment import (
    DEFAULT_MAX_FRAGMENT_SIZE,
    MAX_FRAGMENT_SIZE,
    MIN_FRAGMENT_SIZE,
    ObjectBlock,
    RequestFragment,
    ResponseFragment,
    calculate_available_space,
    fragment_fits,
)
from dnp3.application.header import (
    REQUEST_HEADER_SIZE,
    RESPONSE_HEADER_SIZE,
    RequestHeader,
    ResponseHeader,
)
from dnp3.application.qualifiers import (
    OBJECT_HEADER_SIZE,
    ObjectHeader,
    PrefixCode,
    RangeCode,
)
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN


class TestFragmentConstants:
    """Tests for fragment size constants."""

    def test_min_fragment_size(self) -> None:
        """Minimum fragment size is 249 bytes."""
        assert MIN_FRAGMENT_SIZE == 249

    def test_default_max_fragment_size(self) -> None:
        """Default max fragment size is 2048 bytes."""
        assert DEFAULT_MAX_FRAGMENT_SIZE == 2048

    def test_max_fragment_size(self) -> None:
        """Absolute max fragment size is 65535 bytes."""
        assert MAX_FRAGMENT_SIZE == 65535


class TestObjectBlockCreation:
    """Tests for creating ObjectBlock instances."""

    def test_create_basic(self) -> None:
        """Create basic object block with header only."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header)
        assert block.header == header
        assert block.data == b""

    def test_create_with_data(self) -> None:
        """Create object block with data."""
        header = ObjectHeader(group=30, variation=1, qualifier=0x00)
        data = b"\x01\x02\x03\x04"
        block = ObjectBlock(header=header, data=data)
        assert block.header == header
        assert block.data == data

    def test_immutable(self) -> None:
        """Object block is immutable."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header)
        with pytest.raises(AttributeError):
            block.data = b"\xff"  # type: ignore[misc]


class TestObjectBlockSerialization:
    """Tests for serializing ObjectBlock."""

    def test_serialize_header_only(self) -> None:
        """Serialize block with no data."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header)
        data = block.to_bytes()
        assert data == b"\x01\x02\x00"

    def test_serialize_with_data(self) -> None:
        """Serialize block with data."""
        header = ObjectHeader(group=30, variation=1, qualifier=0x00)
        block = ObjectBlock(header=header, data=b"\xab\xcd")
        data = block.to_bytes()
        assert data == b"\x1e\x01\x00\xab\xcd"


class TestObjectBlockSize:
    """Tests for ObjectBlock.size property."""

    def test_size_header_only(self) -> None:
        """Size is header size (3) when no data."""
        header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=header)
        assert block.size == OBJECT_HEADER_SIZE

    def test_size_with_data(self) -> None:
        """Size includes data length."""
        header = ObjectHeader(group=30, variation=1, qualifier=0x00)
        block = ObjectBlock(header=header, data=b"\x01\x02\x03\x04\x05")
        assert block.size == OBJECT_HEADER_SIZE + 5


class TestRequestFragmentCreation:
    """Tests for creating RequestFragment instances."""

    def test_create_basic(self) -> None:
        """Create basic request fragment with no objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        fragment = RequestFragment(header=header)
        assert fragment.header == header
        assert len(fragment.objects) == 0

    def test_create_with_objects(self) -> None:
        """Create request fragment with objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        obj_header = ObjectHeader.build(
            group=1,
            variation=0,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        block = ObjectBlock(header=obj_header)
        fragment = RequestFragment(header=header, objects=(block,))
        assert len(fragment.objects) == 1
        assert fragment.objects[0] == block


class TestRequestFragmentSerialization:
    """Tests for serializing RequestFragment."""

    def test_serialize_no_objects(self) -> None:
        """Serialize request with no objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        fragment = RequestFragment(header=header)
        data = fragment.to_bytes()
        assert len(data) == REQUEST_HEADER_SIZE
        assert data[0] == 0xC0  # FIR=1, FIN=1
        assert data[1] == 0x01  # READ

    def test_serialize_with_objects(self) -> None:
        """Serialize request with objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        obj_header = ObjectHeader.build(
            group=1,
            variation=0,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        block = ObjectBlock(header=obj_header)
        fragment = RequestFragment(header=header, objects=(block,))
        data = fragment.to_bytes()
        assert len(data) == REQUEST_HEADER_SIZE + OBJECT_HEADER_SIZE
        # Request header
        assert data[0] == 0xC0
        assert data[1] == 0x01
        # Object header
        assert data[2] == 1  # Group 1
        assert data[3] == 0  # Variation 0
        assert data[4] == 0x06  # ALL_OBJECTS qualifier


class TestRequestFragmentSize:
    """Tests for RequestFragment.size property."""

    def test_size_no_objects(self) -> None:
        """Size is header size when no objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        fragment = RequestFragment(header=header)
        assert fragment.size == REQUEST_HEADER_SIZE

    def test_size_with_objects(self) -> None:
        """Size includes all objects."""
        header = RequestHeader.build(function=FunctionCode.READ)
        obj_header = ObjectHeader(group=1, variation=0, qualifier=0x06)
        block1 = ObjectBlock(header=obj_header)
        block2 = ObjectBlock(header=obj_header, data=b"\x01\x02")
        fragment = RequestFragment(header=header, objects=(block1, block2))
        expected = REQUEST_HEADER_SIZE + OBJECT_HEADER_SIZE + (OBJECT_HEADER_SIZE + 2)
        assert fragment.size == expected


class TestRequestFragmentProperties:
    """Tests for RequestFragment properties."""

    def test_is_first(self) -> None:
        """is_first property."""
        first = RequestHeader.build(function=FunctionCode.READ, fir=True, fin=False)
        not_first = RequestHeader.build(function=FunctionCode.READ, fir=False, fin=True)
        assert RequestFragment(header=first).is_first is True
        assert RequestFragment(header=not_first).is_first is False

    def test_is_final(self) -> None:
        """is_final property."""
        final = RequestHeader.build(function=FunctionCode.READ, fir=False, fin=True)
        not_final = RequestHeader.build(function=FunctionCode.READ, fir=True, fin=False)
        assert RequestFragment(header=final).is_final is True
        assert RequestFragment(header=not_final).is_final is False

    def test_is_only(self) -> None:
        """is_only property."""
        only = RequestHeader.build(function=FunctionCode.READ, fir=True, fin=True)
        not_only = RequestHeader.build(function=FunctionCode.READ, fir=True, fin=False)
        assert RequestFragment(header=only).is_only is True
        assert RequestFragment(header=not_only).is_only is False

    def test_sequence(self) -> None:
        """sequence property."""
        header = RequestHeader.build(function=FunctionCode.READ, seq=7)
        fragment = RequestFragment(header=header)
        assert fragment.sequence == 7


class TestResponseFragmentCreation:
    """Tests for creating ResponseFragment instances."""

    def test_create_basic(self) -> None:
        """Create basic response fragment with no objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        fragment = ResponseFragment(header=header)
        assert fragment.header == header
        assert len(fragment.objects) == 0

    def test_create_with_iin(self) -> None:
        """Create response with IIN flags."""
        iin = IIN.DEVICE_RESTART | IIN.NEED_TIME
        header = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=iin)
        fragment = ResponseFragment(header=header)
        assert fragment.header.iin == iin

    def test_create_with_objects(self) -> None:
        """Create response fragment with objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x81")  # Binary point online+on
        fragment = ResponseFragment(header=header, objects=(block,))
        assert len(fragment.objects) == 1


class TestResponseFragmentSerialization:
    """Tests for serializing ResponseFragment."""

    def test_serialize_no_objects(self) -> None:
        """Serialize response with no objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        fragment = ResponseFragment(header=header)
        data = fragment.to_bytes()
        assert len(data) == RESPONSE_HEADER_SIZE
        assert data[0] == 0xC0  # FIR=1, FIN=1
        assert data[1] == 0x81  # RESPONSE
        assert data[2:4] == b"\x00\x00"  # IIN = 0

    def test_serialize_with_iin(self) -> None:
        """Serialize response with IIN flags."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE, iin=IIN.DEVICE_RESTART)
        fragment = ResponseFragment(header=header)
        data = fragment.to_bytes()
        assert data[2] == 0x80  # DEVICE_RESTART in IIN1

    def test_serialize_with_objects(self) -> None:
        """Serialize response with objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x00\x01\x81")
        fragment = ResponseFragment(header=header, objects=(block,))
        data = fragment.to_bytes()
        expected_size = RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + 3
        assert len(data) == expected_size


class TestResponseFragmentSize:
    """Tests for ResponseFragment.size property."""

    def test_size_no_objects(self) -> None:
        """Size is header size when no objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        fragment = ResponseFragment(header=header)
        assert fragment.size == RESPONSE_HEADER_SIZE

    def test_size_with_objects(self) -> None:
        """Size includes all objects."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE)
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x81\x01")
        fragment = ResponseFragment(header=header, objects=(block,))
        expected = RESPONSE_HEADER_SIZE + OBJECT_HEADER_SIZE + 2
        assert fragment.size == expected


class TestResponseFragmentProperties:
    """Tests for ResponseFragment properties."""

    def test_is_first(self) -> None:
        """is_first property."""
        first = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=True, fin=False)
        not_first = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=False, fin=True)
        assert ResponseFragment(header=first).is_first is True
        assert ResponseFragment(header=not_first).is_first is False

    def test_is_final(self) -> None:
        """is_final property."""
        final = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=False, fin=True)
        not_final = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=True, fin=False)
        assert ResponseFragment(header=final).is_final is True
        assert ResponseFragment(header=not_final).is_final is False

    def test_is_only(self) -> None:
        """is_only property."""
        only = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=True, fin=True)
        not_only = ResponseHeader.build(function=FunctionCode.RESPONSE, fir=True, fin=False)
        assert ResponseFragment(header=only).is_only is True
        assert ResponseFragment(header=not_only).is_only is False

    def test_sequence(self) -> None:
        """sequence property."""
        header = ResponseHeader.build(function=FunctionCode.RESPONSE, seq=12)
        fragment = ResponseFragment(header=header)
        assert fragment.sequence == 12

    def test_is_unsolicited(self) -> None:
        """is_unsolicited property."""
        uns = ResponseHeader.build(function=FunctionCode.UNSOLICITED_RESPONSE, uns=True)
        not_uns = ResponseHeader.build(function=FunctionCode.RESPONSE, uns=False)
        assert ResponseFragment(header=uns).is_unsolicited is True
        assert ResponseFragment(header=not_uns).is_unsolicited is False


class TestFragmentFits:
    """Tests for fragment_fits helper."""

    def test_fits_when_equal(self) -> None:
        """Fits when result equals max."""
        assert fragment_fits(current_size=100, addition_size=100, max_size=200) is True

    def test_fits_when_under(self) -> None:
        """Fits when result is under max."""
        assert fragment_fits(current_size=100, addition_size=50, max_size=200) is True

    def test_does_not_fit_when_over(self) -> None:
        """Does not fit when result exceeds max."""
        assert fragment_fits(current_size=100, addition_size=101, max_size=200) is False

    def test_empty_current(self) -> None:
        """Works with empty current size."""
        assert fragment_fits(current_size=0, addition_size=200, max_size=200) is True

    def test_zero_addition(self) -> None:
        """Works with zero addition."""
        assert fragment_fits(current_size=200, addition_size=0, max_size=200) is True


class TestCalculateAvailableSpace:
    """Tests for calculate_available_space helper."""

    def test_empty_fragment(self) -> None:
        """Available space for empty fragment."""
        available = calculate_available_space(
            header_size=REQUEST_HEADER_SIZE,
            objects=(),
            max_size=2048,
        )
        assert available == 2048 - REQUEST_HEADER_SIZE

    def test_with_objects(self) -> None:
        """Available space with existing objects."""
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x01\x02\x03")
        available = calculate_available_space(
            header_size=REQUEST_HEADER_SIZE,
            objects=(block,),
            max_size=100,
        )
        expected = 100 - REQUEST_HEADER_SIZE - (OBJECT_HEADER_SIZE + 3)
        assert available == expected

    def test_full_fragment(self) -> None:
        """No available space when full."""
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x01\x02\x03\x04\x05")
        available = calculate_available_space(
            header_size=REQUEST_HEADER_SIZE,
            objects=(block,),
            max_size=REQUEST_HEADER_SIZE + OBJECT_HEADER_SIZE + 5,
        )
        assert available == 0

    def test_over_full_returns_zero(self) -> None:
        """Returns 0 when already over limit (not negative)."""
        obj_header = ObjectHeader(group=1, variation=2, qualifier=0x00)
        block = ObjectBlock(header=obj_header, data=b"\x01" * 100)
        available = calculate_available_space(
            header_size=REQUEST_HEADER_SIZE,
            objects=(block,),
            max_size=50,  # Way too small
        )
        assert available == 0
