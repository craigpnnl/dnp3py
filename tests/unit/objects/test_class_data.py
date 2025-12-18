"""Tests for Class Data objects (Group 60)."""

from dnp3.objects.base import StaticObject
from dnp3.objects.class_data import (
    CLASS_DATA_GROUP,
    ClassData0,
    ClassData1,
    ClassData2,
    ClassData3,
)


class TestConstants:
    """Tests for class data constants."""

    def test_class_data_group(self) -> None:
        """Class data group is 60."""
        assert CLASS_DATA_GROUP == 60


class TestClassData0:
    """Tests for ClassData0 (g60v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert ClassData0.GROUP == 60
        assert ClassData0.VARIATION == 1

    def test_size(self) -> None:
        """Size is 0 bytes (no data content)."""
        assert ClassData0.SIZE == 0

    def test_is_static_object(self) -> None:
        """ClassData0 is a StaticObject."""
        obj = ClassData0()
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """to_bytes returns empty bytes."""
        obj = ClassData0()
        assert obj.to_bytes() == b""

    def test_from_bytes(self) -> None:
        """from_bytes creates instance."""
        obj = ClassData0.from_bytes(b"")
        assert isinstance(obj, ClassData0)

    def test_from_bytes_ignores_data(self) -> None:
        """from_bytes ignores extra data."""
        obj = ClassData0.from_bytes(b"extra data")
        assert isinstance(obj, ClassData0)

    def test_roundtrip(self) -> None:
        """Roundtrip produces equivalent object."""
        original = ClassData0()
        parsed = ClassData0.from_bytes(original.to_bytes())
        assert parsed == original

    def test_equality(self) -> None:
        """Two instances are equal."""
        obj1 = ClassData0()
        obj2 = ClassData0()
        assert obj1 == obj2


class TestClassData1:
    """Tests for ClassData1 (g60v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert ClassData1.GROUP == 60
        assert ClassData1.VARIATION == 2

    def test_size(self) -> None:
        """Size is 0 bytes (no data content)."""
        assert ClassData1.SIZE == 0

    def test_is_static_object(self) -> None:
        """ClassData1 is a StaticObject."""
        obj = ClassData1()
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """to_bytes returns empty bytes."""
        obj = ClassData1()
        assert obj.to_bytes() == b""

    def test_from_bytes(self) -> None:
        """from_bytes creates instance."""
        obj = ClassData1.from_bytes(b"")
        assert isinstance(obj, ClassData1)

    def test_roundtrip(self) -> None:
        """Roundtrip produces equivalent object."""
        original = ClassData1()
        parsed = ClassData1.from_bytes(original.to_bytes())
        assert parsed == original


class TestClassData2:
    """Tests for ClassData2 (g60v3)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert ClassData2.GROUP == 60
        assert ClassData2.VARIATION == 3

    def test_size(self) -> None:
        """Size is 0 bytes (no data content)."""
        assert ClassData2.SIZE == 0

    def test_is_static_object(self) -> None:
        """ClassData2 is a StaticObject."""
        obj = ClassData2()
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """to_bytes returns empty bytes."""
        obj = ClassData2()
        assert obj.to_bytes() == b""

    def test_from_bytes(self) -> None:
        """from_bytes creates instance."""
        obj = ClassData2.from_bytes(b"")
        assert isinstance(obj, ClassData2)

    def test_roundtrip(self) -> None:
        """Roundtrip produces equivalent object."""
        original = ClassData2()
        parsed = ClassData2.from_bytes(original.to_bytes())
        assert parsed == original


class TestClassData3:
    """Tests for ClassData3 (g60v4)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert ClassData3.GROUP == 60
        assert ClassData3.VARIATION == 4

    def test_size(self) -> None:
        """Size is 0 bytes (no data content)."""
        assert ClassData3.SIZE == 0

    def test_is_static_object(self) -> None:
        """ClassData3 is a StaticObject."""
        obj = ClassData3()
        assert isinstance(obj, StaticObject)

    def test_to_bytes(self) -> None:
        """to_bytes returns empty bytes."""
        obj = ClassData3()
        assert obj.to_bytes() == b""

    def test_from_bytes(self) -> None:
        """from_bytes creates instance."""
        obj = ClassData3.from_bytes(b"")
        assert isinstance(obj, ClassData3)

    def test_roundtrip(self) -> None:
        """Roundtrip produces equivalent object."""
        original = ClassData3()
        parsed = ClassData3.from_bytes(original.to_bytes())
        assert parsed == original
