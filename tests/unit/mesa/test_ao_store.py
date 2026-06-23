"""Tests for MESA Analog Output store module.

RED phase: these tests target classes that do not exist yet.
All tests must fail with ImportError until ao_store.py is implemented.
"""

import pytest

from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue


class TestAnalogOutputValueConstruction:
    """Tests for AnalogOutputValue dataclass creation."""

    def test_construct_with_all_fields(self) -> None:
        """AnalogOutputValue can be constructed with all fields specified."""
        ao = AnalogOutputValue(
            index=0,
            value=50.0,
            minimum=0.0,
            maximum=100.0,
            multiplier=2.0,
            offset=1.5,
            units="MW",
            description="Active power setpoint",
        )
        assert ao.index == 0
        assert ao.value == 50.0
        assert ao.minimum == 0.0
        assert ao.maximum == 100.0
        assert ao.multiplier == 2.0
        assert ao.offset == 1.5
        assert ao.units == "MW"
        assert ao.description == "Active power setpoint"

    def test_default_multiplier_is_one(self) -> None:
        """Multiplier defaults to 1.0 when not provided."""
        ao = AnalogOutputValue(index=1, value=10.0, minimum=0.0, maximum=100.0)
        assert ao.multiplier == 1.0

    def test_default_offset_is_zero(self) -> None:
        """Offset defaults to 0.0 when not provided."""
        ao = AnalogOutputValue(index=1, value=10.0, minimum=0.0, maximum=100.0)
        assert ao.offset == 0.0

    def test_default_units_is_empty_string(self) -> None:
        """Units defaults to empty string when not provided."""
        ao = AnalogOutputValue(index=1, value=10.0, minimum=0.0, maximum=100.0)
        assert ao.units == ""

    def test_default_description_is_empty_string(self) -> None:
        """Description defaults to empty string when not provided."""
        ao = AnalogOutputValue(index=1, value=10.0, minimum=0.0, maximum=100.0)
        assert ao.description == ""


class TestAnalogOutputValueImmutability:
    """Tests that AnalogOutputValue is a frozen (immutable) dataclass."""

    def test_cannot_assign_value(self) -> None:
        """Assigning to value field raises an error."""
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        with pytest.raises((AttributeError, TypeError)):
            ao.value = 99.0  # type: ignore[misc]

    def test_cannot_assign_index(self) -> None:
        """Assigning to index field raises an error."""
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        with pytest.raises((AttributeError, TypeError)):
            ao.index = 5  # type: ignore[misc]

    def test_cannot_assign_minimum(self) -> None:
        """Assigning to minimum field raises an error."""
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        with pytest.raises((AttributeError, TypeError)):
            ao.minimum = -10.0  # type: ignore[misc]


class TestAnalogOutputStoreAdd:
    """Tests for AnalogOutputStore.add method."""

    def test_add_then_get_returns_value(self) -> None:
        """Adding a value and retrieving it returns the same object."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        store.add(ao)
        result = store.get(0)
        assert result is ao

    def test_add_duplicate_index_raises_value_error(self) -> None:
        """Adding a value with an existing index raises ValueError."""
        store = AnalogOutputStore()
        ao1 = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        ao2 = AnalogOutputValue(index=0, value=75.0, minimum=0.0, maximum=100.0)
        store.add(ao1)
        with pytest.raises(ValueError):
            store.add(ao2)


class TestAnalogOutputStoreGet:
    """Tests for AnalogOutputStore.get method."""

    def test_get_nonexistent_returns_none(self) -> None:
        """Getting a nonexistent index returns None."""
        store = AnalogOutputStore()
        assert store.get(999) is None


class TestAnalogOutputStoreSetValue:
    """Tests for AnalogOutputStore.set_value method."""

    def test_set_value_returns_new_object(self) -> None:
        """set_value returns a new AnalogOutputValue, not the original."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        store.add(ao)
        updated = store.set_value(0, 75.0)
        assert updated is not ao
        assert updated.value == 75.0

    def test_set_value_preserves_other_fields(self) -> None:
        """set_value preserves index, minimum, maximum, multiplier, offset, units, description."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(
            index=5,
            value=10.0,
            minimum=0.0,
            maximum=100.0,
            multiplier=2.0,
            offset=1.5,
            units="kW",
            description="Power output",
        )
        store.add(ao)
        updated = store.set_value(5, 60.0)
        assert updated.index == 5
        assert updated.minimum == 0.0
        assert updated.maximum == 100.0
        assert updated.multiplier == 2.0
        assert updated.offset == 1.5
        assert updated.units == "kW"
        assert updated.description == "Power output"

    def test_set_value_original_unchanged(self) -> None:
        """The original AnalogOutputValue in the store is replaced, not mutated."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        store.add(ao)
        store.set_value(0, 75.0)
        assert ao.value == 50.0  # original frozen object unchanged

    def test_set_value_updates_store(self) -> None:
        """After set_value, get returns the new value."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=0.0, maximum=100.0)
        store.add(ao)
        store.set_value(0, 75.0)
        result = store.get(0)
        assert result is not None
        assert result.value == 75.0

    def test_set_value_at_minimum_boundary(self) -> None:
        """set_value at exactly the minimum succeeds."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=10.0, maximum=100.0)
        store.add(ao)
        updated = store.set_value(0, 10.0)
        assert updated.value == 10.0

    def test_set_value_at_maximum_boundary(self) -> None:
        """set_value at exactly the maximum succeeds."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=10.0, maximum=100.0)
        store.add(ao)
        updated = store.set_value(0, 100.0)
        assert updated.value == 100.0

    def test_set_value_below_minimum_raises_value_error(self) -> None:
        """set_value below minimum raises ValueError."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=10.0, maximum=100.0)
        store.add(ao)
        with pytest.raises(ValueError):
            store.set_value(0, 9.99)

    def test_set_value_above_maximum_raises_value_error(self) -> None:
        """set_value above maximum raises ValueError."""
        store = AnalogOutputStore()
        ao = AnalogOutputValue(index=0, value=50.0, minimum=10.0, maximum=100.0)
        store.add(ao)
        with pytest.raises(ValueError):
            store.set_value(0, 100.01)

    def test_set_value_nonexistent_index_raises_key_error(self) -> None:
        """set_value on a nonexistent index raises KeyError."""
        store = AnalogOutputStore()
        with pytest.raises(KeyError):
            store.set_value(42, 50.0)


class TestAnalogOutputStoreGetAll:
    """Tests for AnalogOutputStore.get_all method."""

    def test_get_all_returns_sorted_by_index(self) -> None:
        """get_all returns values sorted by index regardless of insertion order."""
        store = AnalogOutputStore()
        ao3 = AnalogOutputValue(index=30, value=1.0, minimum=0.0, maximum=10.0)
        ao1 = AnalogOutputValue(index=10, value=2.0, minimum=0.0, maximum=10.0)
        ao2 = AnalogOutputValue(index=20, value=3.0, minimum=0.0, maximum=10.0)
        store.add(ao3)
        store.add(ao1)
        store.add(ao2)
        result = store.get_all()
        assert [ao.index for ao in result] == [10, 20, 30]

    def test_get_all_empty_store_returns_empty_list(self) -> None:
        """get_all on an empty store returns an empty list."""
        store = AnalogOutputStore()
        assert store.get_all() == []


class TestAnalogOutputStoreDunderMethods:
    """Tests for AnalogOutputStore __len__ and __contains__."""

    def test_len_empty_store(self) -> None:
        """Empty store has length 0."""
        store = AnalogOutputStore()
        assert len(store) == 0

    def test_len_after_adds(self) -> None:
        """Length reflects number of added entries."""
        store = AnalogOutputStore()
        store.add(AnalogOutputValue(index=0, value=1.0, minimum=0.0, maximum=10.0))
        store.add(AnalogOutputValue(index=1, value=2.0, minimum=0.0, maximum=10.0))
        store.add(AnalogOutputValue(index=2, value=3.0, minimum=0.0, maximum=10.0))
        assert len(store) == 3

    def test_contains_existing_index(self) -> None:
        """__contains__ returns True for an existing index."""
        store = AnalogOutputStore()
        store.add(AnalogOutputValue(index=5, value=1.0, minimum=0.0, maximum=10.0))
        assert 5 in store

    def test_contains_missing_index(self) -> None:
        """__contains__ returns False for a missing index."""
        store = AnalogOutputStore()
        assert 5 not in store
