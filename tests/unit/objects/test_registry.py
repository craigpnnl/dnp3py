"""Tests for DNP3 object registry."""

import pytest

from dnp3.objects.base import GroupVariation, StaticObject
from dnp3.objects.registry import (
    clear_registry,
    get_registered,
    get_registry_copy,
    get_size,
    is_registered,
    lookup,
    lookup_gv,
    register,
)


class TestObjectForRegistry(StaticObject):
    """Test object for registry tests."""

    GROUP = 99
    VARIATION = 1
    SIZE = 2

    def to_bytes(self) -> bytes:
        return b"\x00\x00"

    @classmethod
    def from_bytes(cls, data: bytes) -> "TestObjectForRegistry":
        return cls()


class TestObjectForRegistry2(StaticObject):
    """Second test object for registry tests."""

    GROUP = 99
    VARIATION = 2
    SIZE = 4

    def to_bytes(self) -> bytes:
        return b"\x00\x00\x00\x00"

    @classmethod
    def from_bytes(cls, data: bytes) -> "TestObjectForRegistry2":
        return cls()


class TestObjectVariableSize(StaticObject):
    """Test object with variable size."""

    GROUP = 99
    VARIATION = 3
    SIZE = None

    def to_bytes(self) -> bytes:
        return b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "TestObjectVariableSize":
        return cls()


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Clear registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


class TestRegisterDecorator:
    """Tests for register decorator."""

    def test_register_object(self) -> None:
        """Register an object class."""

        @register
        class TestObj(StaticObject):
            GROUP = 100
            VARIATION = 1
            SIZE = 1

            def to_bytes(self) -> bytes:
                return b"\x00"

            @classmethod
            def from_bytes(cls, data: bytes) -> "TestObj":
                return cls()

        assert is_registered(100, 1)
        assert lookup(100, 1) is TestObj

    def test_register_returns_class(self) -> None:
        """Register decorator returns the class."""

        @register
        class TestObj(StaticObject):
            GROUP = 101
            VARIATION = 1
            SIZE = 1

            def to_bytes(self) -> bytes:
                return b"\x00"

            @classmethod
            def from_bytes(cls, data: bytes) -> "TestObj":
                return cls()

        assert TestObj.GROUP == 101

    def test_register_missing_group_raises(self) -> None:
        """Register class without GROUP raises error."""
        with pytest.raises(ValueError, match="must define GROUP and VARIATION"):

            @register
            class BadObj(StaticObject):  # type: ignore[type-var]
                VARIATION = 1
                SIZE = 1

                def to_bytes(self) -> bytes:
                    return b""

                @classmethod
                def from_bytes(cls, data: bytes) -> "BadObj":
                    return cls()

    def test_register_missing_variation_raises(self) -> None:
        """Register class without VARIATION raises error."""
        with pytest.raises(ValueError, match="must define GROUP and VARIATION"):

            @register
            class BadObj(StaticObject):  # type: ignore[type-var]
                GROUP = 1
                SIZE = 1

                def to_bytes(self) -> bytes:
                    return b""

                @classmethod
                def from_bytes(cls, data: bytes) -> "BadObj":
                    return cls()

    def test_register_duplicate_raises(self) -> None:
        """Register same group/variation twice raises error."""

        @register
        class TestObj1(StaticObject):
            GROUP = 102
            VARIATION = 1
            SIZE = 1

            def to_bytes(self) -> bytes:
                return b"\x00"

            @classmethod
            def from_bytes(cls, data: bytes) -> "TestObj1":
                return cls()

        with pytest.raises(ValueError, match="already registered"):

            @register
            class TestObj2(StaticObject):
                GROUP = 102
                VARIATION = 1
                SIZE = 2

                def to_bytes(self) -> bytes:
                    return b"\x00\x00"

                @classmethod
                def from_bytes(cls, data: bytes) -> "TestObj2":
                    return cls()


class TestLookup:
    """Tests for lookup function."""

    def test_lookup_registered(self) -> None:
        """Lookup returns registered class."""
        register(TestObjectForRegistry)
        result = lookup(99, 1)
        assert result is TestObjectForRegistry

    def test_lookup_not_registered(self) -> None:
        """Lookup returns None for unregistered."""
        result = lookup(255, 255)
        assert result is None

    def test_lookup_wrong_variation(self) -> None:
        """Lookup returns None for wrong variation."""
        register(TestObjectForRegistry)
        result = lookup(99, 99)
        assert result is None


class TestLookupGV:
    """Tests for lookup_gv function."""

    def test_lookup_gv_registered(self) -> None:
        """Lookup by GroupVariation returns registered class."""
        register(TestObjectForRegistry)
        gv = GroupVariation(group=99, variation=1)
        result = lookup_gv(gv)
        assert result is TestObjectForRegistry

    def test_lookup_gv_not_registered(self) -> None:
        """Lookup by GroupVariation returns None for unregistered."""
        gv = GroupVariation(group=255, variation=255)
        result = lookup_gv(gv)
        assert result is None


class TestGetRegistered:
    """Tests for get_registered function."""

    def test_empty_registry(self) -> None:
        """Empty registry returns empty list."""
        result = get_registered()
        assert result == []

    def test_single_registration(self) -> None:
        """Single registration in list."""
        register(TestObjectForRegistry)
        result = get_registered()
        assert result == [(99, 1)]

    def test_multiple_registrations_sorted(self) -> None:
        """Multiple registrations returned sorted."""
        register(TestObjectForRegistry2)  # 99, 2
        register(TestObjectForRegistry)  # 99, 1
        result = get_registered()
        assert result == [(99, 1), (99, 2)]


class TestGetSize:
    """Tests for get_size function."""

    def test_get_size_registered(self) -> None:
        """Get size of registered object."""
        register(TestObjectForRegistry)
        result = get_size(99, 1)
        assert result == 2

    def test_get_size_not_registered(self) -> None:
        """Get size of unregistered object returns None."""
        result = get_size(255, 255)
        assert result is None

    def test_get_size_variable_size(self) -> None:
        """Get size of variable-size object returns None."""
        register(TestObjectVariableSize)
        result = get_size(99, 3)
        assert result is None


class TestIsRegistered:
    """Tests for is_registered function."""

    def test_is_registered_true(self) -> None:
        """is_registered returns True for registered."""
        register(TestObjectForRegistry)
        assert is_registered(99, 1) is True

    def test_is_registered_false(self) -> None:
        """is_registered returns False for unregistered."""
        assert is_registered(255, 255) is False


class TestClearRegistry:
    """Tests for clear_registry function."""

    def test_clear_removes_all(self) -> None:
        """Clear removes all registrations."""
        register(TestObjectForRegistry)
        register(TestObjectForRegistry2)
        assert len(get_registered()) == 2
        clear_registry()
        assert len(get_registered()) == 0


class TestGetRegistryCopy:
    """Tests for get_registry_copy function."""

    def test_get_copy(self) -> None:
        """Get a copy of the registry."""
        register(TestObjectForRegistry)
        copy = get_registry_copy()
        assert (99, 1) in copy
        assert copy[(99, 1)] is TestObjectForRegistry

    def test_copy_is_independent(self) -> None:
        """Copy is independent of original."""
        register(TestObjectForRegistry)
        copy = get_registry_copy()
        clear_registry()
        # Original cleared, but copy still has it
        assert (99, 1) in copy
