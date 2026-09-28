"""Tests for the wire-layout table.

Expected lengths are derived by hand from the IEEE 1815-2012 Annex A formal
structures and the clause 4 worked examples, never from this library's encoders.
"""

import pytest

import dnp3.objects  # noqa: F401  (populates the registry)
from dnp3.objects import registry
from dnp3.objects.layout import (
    LAYOUTS,
    PointKind,
    TimeKind,
    ValueCodec,
    WireLayout,
    data_length,
    lookup,
    object_width,
)

# Captured at collection: tests/unit/objects/test_registry.py clears the global
# registry and never restores it, so reading it at run time depends on test order.
_REGISTERED_SIZES = {pair: registry.get_size(*pair) for pair in registry.get_registered()}


class TestRegistryConsistency:
    """The layout table and the registry must agree on every registered width."""

    def test_registry_snapshot_is_populated(self) -> None:
        assert (30, 1) in _REGISTERED_SIZES
        assert len(_REGISTERED_SIZES) >= 43

    @pytest.mark.parametrize("pair", sorted(_REGISTERED_SIZES), ids=lambda p: f"g{p[0]}v{p[1]}")
    def test_layout_width_equals_registered_size(self, pair: tuple[int, int]) -> None:
        assert lookup(*pair) is not None, f"g{pair[0]}v{pair[1]} is registered but has no layout"
        assert object_width(*pair) == _REGISTERED_SIZES[pair]


class TestLayoutFields:
    """Field values for representative layouts, read from Annex A."""

    def test_binary_input_packed(self) -> None:
        # A.2.1.2.2: BSTRn, one bit per point, no flags.
        layout = lookup(1, 1)
        assert layout == WireLayout(PointKind.BINARY_INPUT, 0, 1, False, ValueCodec.PACKED, TimeKind.NONE)
        assert object_width(1, 1) is None

    def test_binary_output_packed(self) -> None:
        # A.6.1.2.2: BSTRn, one bit per point.
        layout = lookup(10, 1)
        assert layout is not None
        assert (layout.point_kind, layout.bits_per_point, layout.width) == (PointKind.BINARY_OUTPUT, 1, 0)

    def test_double_bit_input_packed(self) -> None:
        # A.4.1.2.2: SET of n UINT2, two bits per point.
        layout = lookup(3, 1)
        assert layout is not None
        assert (layout.point_kind, layout.bits_per_point, layout.width) == (PointKind.DOUBLE_BIT_INPUT, 2, 0)
        assert layout.is_packed

    def test_binary_input_event_with_time(self) -> None:
        # A.3.2: flag octet then DNP3TIME (UINT48).
        layout = lookup(2, 2)
        assert layout is not None
        assert layout.has_flags
        assert layout.codec is ValueCodec.FLAG_STATE
        assert layout.time is TimeKind.ABSOLUTE
        assert (layout.width, layout.value_width) == (7, 0)

    def test_binary_input_event_relative_time(self) -> None:
        # A.3.3: flag octet then UINT16 relative time.
        layout = lookup(2, 3)
        assert layout is not None
        assert (layout.width, layout.time) == (3, TimeKind.RELATIVE)

    def test_analog_float_event_with_time(self) -> None:
        # A.16.7: flag octet, FLT32, DNP3TIME.
        layout = lookup(32, 7)
        assert layout is not None
        assert (layout.point_kind, layout.codec) == (PointKind.ANALOG_INPUT, ValueCodec.FLOAT32)
        assert (layout.width, layout.value_width, layout.time) == (11, 4, TimeKind.ABSOLUTE)

    def test_analog_input_16_without_flag(self) -> None:
        # A.14.4: INT16 only.
        layout = lookup(30, 4)
        assert layout is not None
        assert (layout.has_flags, layout.codec, layout.value_width, layout.width) == (False, ValueCodec.INT, 2, 2)

    def test_frozen_counter_with_time_is_not_the_counter_layout(self) -> None:
        # A.11.5: flag octet, UINT32, DNP3TIME; A.10.5 (g20v5) is UINT32 alone.
        frozen = lookup(21, 5)
        counter = lookup(20, 5)
        assert frozen is not None
        assert counter is not None
        assert (frozen.point_kind, frozen.has_flags, frozen.codec, frozen.width) == (
            PointKind.FROZEN_COUNTER,
            True,
            ValueCodec.UINT,
            11,
        )
        assert (counter.point_kind, counter.has_flags, counter.width) == (PointKind.COUNTER, False, 4)

    def test_class_objects_carry_no_data(self) -> None:
        # A.26: class objects appear only in requests, with no object data.
        for variation in (1, 2, 3, 4):
            assert object_width(60, variation) == 0

    def test_unknown_pair(self) -> None:
        # A.14 defines g30v1 to g30v6 only.
        assert lookup(30, 99) is None
        assert object_width(30, 99) is None

    def test_table_is_read_only(self) -> None:
        with pytest.raises(TypeError):
            LAYOUTS[(30, 99)] = LAYOUTS[(30, 1)]  # type: ignore[index]


class TestLayoutValidation:
    """A layout that could not describe a real object is refused at construction."""

    def test_packed_layout_with_octet_width_is_refused(self) -> None:
        with pytest.raises(ValueError, match="packed"):
            WireLayout(PointKind.BINARY_INPUT, 1, 1, False, ValueCodec.PACKED, TimeKind.NONE)

    def test_packed_layout_with_flags_is_refused(self) -> None:
        with pytest.raises(ValueError, match="packed"):
            WireLayout(PointKind.BINARY_INPUT, 0, 1, True, ValueCodec.PACKED, TimeKind.NONE)

    def test_width_smaller_than_flags_and_time_is_refused(self) -> None:
        with pytest.raises(ValueError, match="width"):
            WireLayout(PointKind.ANALOG_INPUT, 6, 0, True, ValueCodec.INT, TimeKind.ABSOLUTE)


def _layout(group: int, variation: int) -> WireLayout:
    layout = lookup(group, variation)
    assert layout is not None
    return layout


class TestDataLength:
    """Octets of object data a header's count and prefix imply."""

    @pytest.mark.parametrize(
        ("group", "variation", "count", "expected"),
        [
            # A.2.1.2.2 (g1v1, 1 bit per point, last octet padded with 0).
            (1, 1, 1, 1),
            (1, 1, 8, 1),
            (1, 1, 9, 2),
            # EX 4-10 (clause 4, p. 43): 18 points in the 3 octets 0F AA 03.
            (1, 1, 18, 3),
            # A.6.1.2.2 (g10v1, 1 bit per point).
            (10, 1, 16, 2),
            (10, 1, 17, 3),
            # A.4.1.2.2 (g3v1, 2 bits per point).
            (3, 1, 1, 1),
            (3, 1, 4, 1),
            (3, 1, 5, 2),
            (3, 1, 8, 2),
        ],
    )
    def test_packed(self, group: int, variation: int, count: int, expected: int) -> None:
        assert data_length(_layout(group, variation), count, 0) == expected

    @pytest.mark.parametrize(("group", "variation"), [(1, 1), (10, 1), (3, 1)])
    def test_packed_zero_count_is_zero(self, group: int, variation: int) -> None:
        assert data_length(_layout(group, variation), 0, 0) == 0

    @pytest.mark.parametrize("prefix_width", [1, 2, 4])
    @pytest.mark.parametrize("count", [0, 1, 18])
    def test_packed_with_index_prefix_is_undefined(self, prefix_width: int, count: int) -> None:
        # A.2.1 and A.4.1 define packing only over a contiguous index range.
        assert data_length(_layout(1, 1), count, prefix_width) is None
        assert data_length(_layout(3, 1), count, prefix_width) is None

    @pytest.mark.parametrize(
        ("group", "variation", "count", "prefix_width", "expected"),
        [
            # EX 4-9 (clause 4, p. 43): four g30v4 points in 88 13 20 4E 50 FB 60 00.
            (30, 4, 4, 0, 8),
            # EX 4-11 (clause 4, p. 44): one g2v1 event with a 1-octet index, 14 81.
            (2, 1, 1, 1, 2),
            # EX 4-11: one g32v2 event with a 1-octet index, 0B 20 FF FF.
            (32, 2, 1, 1, 4),
            # A.14.1 (flag, INT32): 5 octets per point.
            (30, 1, 4, 0, 20),
            (30, 1, 4, 2, 28),
            # A.16.3 (flag, INT32, DNP3TIME): 11 octets per point.
            (32, 3, 2, 2, 26),
            # A.3.2 (flag, DNP3TIME): 7 octets per point.
            (2, 2, 3, 4, 33),
            (30, 1, 0, 2, 0),
        ],
    )
    def test_octet_aligned(self, group: int, variation: int, count: int, prefix_width: int, expected: int) -> None:
        assert data_length(_layout(group, variation), count, prefix_width) == expected

    @pytest.mark.parametrize(("count", "prefix_width"), [(-1, 0), (1, -1)])
    def test_negative_arguments_are_refused(self, count: int, prefix_width: int) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            data_length(_layout(30, 1), count, prefix_width)
