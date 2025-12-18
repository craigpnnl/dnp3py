"""Tests for DNP3 object base classes."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import (
    QUALITY_SIZE,
    SIZE_1_BYTE,
    SIZE_2_BYTES,
    SIZE_4_BYTES,
    SIZE_5_BYTES,
    SIZE_6_BYTES,
    SIZE_7_BYTES,
    SIZE_8_BYTES,
    SIZE_9_BYTES,
    SIZE_11_BYTES,
    DNP3Object,
    EventObject,
    GroupVariation,
    PointValue,
    StaticObject,
    TimestampedValue,
)


class TestSizeConstants:
    """Tests for size constants."""

    def test_size_1_byte(self) -> None:
        """SIZE_1_BYTE is 1."""
        assert SIZE_1_BYTE == 1

    def test_size_2_bytes(self) -> None:
        """SIZE_2_BYTES is 2."""
        assert SIZE_2_BYTES == 2

    def test_size_4_bytes(self) -> None:
        """SIZE_4_BYTES is 4."""
        assert SIZE_4_BYTES == 4

    def test_size_5_bytes(self) -> None:
        """SIZE_5_BYTES is 5."""
        assert SIZE_5_BYTES == 5

    def test_size_6_bytes(self) -> None:
        """SIZE_6_BYTES is 6."""
        assert SIZE_6_BYTES == 6

    def test_size_7_bytes(self) -> None:
        """SIZE_7_BYTES is 7."""
        assert SIZE_7_BYTES == 7

    def test_size_8_bytes(self) -> None:
        """SIZE_8_BYTES is 8."""
        assert SIZE_8_BYTES == 8

    def test_size_9_bytes(self) -> None:
        """SIZE_9_BYTES is 9."""
        assert SIZE_9_BYTES == 9

    def test_size_11_bytes(self) -> None:
        """SIZE_11_BYTES is 11."""
        assert SIZE_11_BYTES == 11

    def test_quality_size(self) -> None:
        """QUALITY_SIZE is 1."""
        assert QUALITY_SIZE == 1


class TestGroupVariation:
    """Tests for GroupVariation dataclass."""

    def test_create_basic(self) -> None:
        """Create basic group/variation."""
        gv = GroupVariation(group=1, variation=2)
        assert gv.group == 1
        assert gv.variation == 2

    def test_str_format(self) -> None:
        """String format is g{group}v{variation}."""
        gv = GroupVariation(group=30, variation=1)
        assert str(gv) == "g30v1"

    def test_group_negative_raises(self) -> None:
        """Negative group raises error."""
        with pytest.raises(ValueError, match=r"Group.*out of range"):
            GroupVariation(group=-1, variation=0)

    def test_group_too_large_raises(self) -> None:
        """Group > 255 raises error."""
        with pytest.raises(ValueError, match=r"Group.*out of range"):
            GroupVariation(group=256, variation=0)

    def test_variation_negative_raises(self) -> None:
        """Negative variation raises error."""
        with pytest.raises(ValueError, match=r"Variation.*out of range"):
            GroupVariation(group=0, variation=-1)

    def test_variation_too_large_raises(self) -> None:
        """Variation > 255 raises error."""
        with pytest.raises(ValueError, match=r"Variation.*out of range"):
            GroupVariation(group=0, variation=256)

    def test_immutable(self) -> None:
        """GroupVariation is immutable."""
        gv = GroupVariation(group=1, variation=2)
        with pytest.raises(AttributeError):
            gv.group = 10  # type: ignore[misc]

    @given(st.integers(min_value=0, max_value=255), st.integers(min_value=0, max_value=255))
    def test_valid_range(self, group: int, variation: int) -> None:
        """All valid group/variation combinations work."""
        gv = GroupVariation(group=group, variation=variation)
        assert gv.group == group
        assert gv.variation == variation

    def test_equality(self) -> None:
        """GroupVariation equality works."""
        gv1 = GroupVariation(group=1, variation=2)
        gv2 = GroupVariation(group=1, variation=2)
        gv3 = GroupVariation(group=1, variation=3)
        assert gv1 == gv2
        assert gv1 != gv3

    def test_hash(self) -> None:
        """GroupVariation is hashable."""
        gv = GroupVariation(group=1, variation=2)
        d = {gv: "test"}
        assert d[GroupVariation(1, 2)] == "test"


class ConcreteStaticObject(StaticObject):
    """Concrete static object for testing."""

    GROUP = 1
    VARIATION = 1
    SIZE = 1

    def __init__(self, value: int) -> None:
        self._value = value

    def to_bytes(self) -> bytes:
        return bytes([self._value])

    @classmethod
    def from_bytes(cls, data: bytes) -> "ConcreteStaticObject":
        if not data:
            msg = "Empty data"
            raise ValueError(msg)
        return cls(value=data[0])


class ConcreteEventObject(EventObject):
    """Concrete event object for testing."""

    GROUP = 2
    VARIATION = 1
    SIZE = 1

    def __init__(self, value: int) -> None:
        self._value = value

    def to_bytes(self) -> bytes:
        return bytes([self._value])

    @classmethod
    def from_bytes(cls, data: bytes) -> "ConcreteEventObject":
        if not data:
            msg = "Empty data"
            raise ValueError(msg)
        return cls(value=data[0])


class TestDNP3ObjectBase:
    """Tests for DNP3Object base class through concrete implementations."""

    def test_group_variation_property(self) -> None:
        """group_variation() returns correct GroupVariation."""
        gv = ConcreteStaticObject.group_variation()
        assert gv.group == 1
        assert gv.variation == 1

    def test_size_property(self) -> None:
        """size() returns SIZE class variable."""
        assert ConcreteStaticObject.size() == 1

    def test_to_bytes(self) -> None:
        """to_bytes serializes object."""
        obj = ConcreteStaticObject(value=0x81)
        assert obj.to_bytes() == b"\x81"

    def test_from_bytes(self) -> None:
        """from_bytes parses object."""
        obj = ConcreteStaticObject.from_bytes(b"\x81")
        assert obj._value == 0x81


class TestStaticObject:
    """Tests for StaticObject base class."""

    def test_is_dnp3_object(self) -> None:
        """StaticObject is a DNP3Object."""
        obj = ConcreteStaticObject(value=0)
        assert isinstance(obj, DNP3Object)

    def test_is_static_object(self) -> None:
        """ConcreteStaticObject is a StaticObject."""
        obj = ConcreteStaticObject(value=0)
        assert isinstance(obj, StaticObject)


class TestEventObject:
    """Tests for EventObject base class."""

    def test_is_dnp3_object(self) -> None:
        """EventObject is a DNP3Object."""
        obj = ConcreteEventObject(value=0)
        assert isinstance(obj, DNP3Object)

    def test_is_event_object(self) -> None:
        """ConcreteEventObject is an EventObject."""
        obj = ConcreteEventObject(value=0)
        assert isinstance(obj, EventObject)


class TestPointValue:
    """Tests for PointValue dataclass."""

    def test_create_basic(self) -> None:
        """Create basic point value."""
        obj = ConcreteStaticObject(value=0x81)
        pv = PointValue(index=5, value=obj)
        assert pv.index == 5
        assert pv.value == obj

    def test_index_zero_valid(self) -> None:
        """Index 0 is valid."""
        obj = ConcreteStaticObject(value=0)
        pv = PointValue(index=0, value=obj)
        assert pv.index == 0

    def test_index_negative_raises(self) -> None:
        """Negative index raises error."""
        obj = ConcreteStaticObject(value=0)
        with pytest.raises(ValueError, match="cannot be negative"):
            PointValue(index=-1, value=obj)

    def test_immutable(self) -> None:
        """PointValue is immutable."""
        obj = ConcreteStaticObject(value=0)
        pv = PointValue(index=5, value=obj)
        with pytest.raises(AttributeError):
            pv.index = 10  # type: ignore[misc]


class TestTimestampedValue:
    """Tests for TimestampedValue dataclass."""

    def test_create_basic(self) -> None:
        """Create timestamped value."""
        obj = ConcreteEventObject(value=0x81)
        ts = DNP3Timestamp(milliseconds=1000)
        tv = TimestampedValue(value=obj, timestamp=ts)
        assert tv.value == obj
        assert tv.timestamp == ts

    def test_immutable(self) -> None:
        """TimestampedValue is immutable."""
        obj = ConcreteEventObject(value=0)
        ts = DNP3Timestamp(milliseconds=0)
        tv = TimestampedValue(value=obj, timestamp=ts)
        with pytest.raises(AttributeError):
            tv.timestamp = DNP3Timestamp(milliseconds=1000)  # type: ignore[misc]
