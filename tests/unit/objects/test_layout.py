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
    layout_for,
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
        assert layout_for(*pair) is not None, f"g{pair[0]}v{pair[1]} is registered but has no layout"
        assert object_width(*pair) == _REGISTERED_SIZES[pair]


_BI = PointKind.BINARY_INPUT
_BO = PointKind.BINARY_OUTPUT
_DBI = PointKind.DOUBLE_BIT_INPUT
_CT = PointKind.COUNTER
_FC = PointKind.FROZEN_COUNTER
_AI = PointKind.ANALOG_INPUT
_AO = PointKind.ANALOG_OUTPUT
_FAI = PointKind.FROZEN_ANALOG_INPUT
_NO = TimeKind.NONE
_ABS = TimeKind.ABSOLUTE
_REL = TimeKind.RELATIVE
_PK = ValueCodec.PACKED
_ST = ValueCodec.FLAG_STATE
_INT = ValueCodec.INT
_UINT = ValueCodec.UINT
_F32 = ValueCodec.FLOAT32
_F64 = ValueCodec.FLOAT64
_REC = ValueCodec.RECORD

# Every row, hand-derived from the Annex A formal structure named beside it:
# (group, variation): (point kind, width, bits per point, flags, codec, time).
_EXPECTED_ROWS = {
    (1, 1): (_BI, 0, 1, False, _PK, _NO),  # A.2.1: BSTRn
    (1, 2): (_BI, 1, 0, True, _ST, _NO),  # A.2.2: flag octet
    (2, 1): (_BI, 1, 0, True, _ST, _NO),  # A.3.1: flag octet
    (2, 2): (_BI, 7, 0, True, _ST, _ABS),  # A.3.2: flag, DNP3TIME
    (2, 3): (_BI, 3, 0, True, _ST, _REL),  # A.3.3: flag, UINT16 relative time
    (3, 1): (_DBI, 0, 2, False, _PK, _NO),  # A.4.1: UINT2 per point
    (3, 2): (_DBI, 1, 0, True, _ST, _NO),  # A.4.2: flag octet, UINT2 state
    (4, 1): (_DBI, 1, 0, True, _ST, _NO),  # A.5.1: flag octet, UINT2 state
    (4, 2): (_DBI, 7, 0, True, _ST, _ABS),  # A.5.2: flag, state, DNP3TIME
    (4, 3): (_DBI, 3, 0, True, _ST, _REL),  # A.5.3: flag, state, UINT16 relative time
    (10, 1): (_BO, 0, 1, False, _PK, _NO),  # A.6.1: BSTRn
    (10, 2): (_BO, 1, 0, True, _ST, _NO),  # A.6.2: flag octet
    (11, 1): (_BO, 1, 0, True, _ST, _NO),  # A.7.1: flag octet
    (11, 2): (_BO, 7, 0, True, _ST, _ABS),  # A.7.2: flag, DNP3TIME
    (12, 1): (PointKind.BINARY_COMMAND, 11, 0, False, ValueCodec.RECORD, _NO),  # A.8.1: 1+1+4+4+1
    (13, 1): (PointKind.BINARY_COMMAND_EVENT, 1, 0, False, _REC, _NO),  # A.9.1: UINT7 status, BSTR1 state
    (13, 2): (PointKind.BINARY_COMMAND_EVENT, 7, 0, False, _REC, _ABS),  # A.9.2: status, state, DNP3TIME
    (20, 1): (_CT, 5, 0, True, _UINT, _NO),  # A.10.1: flag, UINT32
    (20, 2): (_CT, 3, 0, True, _UINT, _NO),  # A.10.2: flag, UINT16
    (20, 3): (_CT, 5, 0, True, _UINT, _NO),  # A.10.3: flag, UINT32, delta
    (20, 4): (_CT, 3, 0, True, _UINT, _NO),  # A.10.4: flag, UINT16, delta
    (20, 5): (_CT, 4, 0, False, _UINT, _NO),  # A.10.5: UINT32
    (20, 6): (_CT, 2, 0, False, _UINT, _NO),  # A.10.6: UINT16
    (20, 7): (_CT, 4, 0, False, _UINT, _NO),  # A.10.7: UINT32, delta
    (20, 8): (_CT, 2, 0, False, _UINT, _NO),  # A.10.8: UINT16, delta
    (21, 1): (_FC, 5, 0, True, _UINT, _NO),  # A.11.1: flag, UINT32
    (21, 2): (_FC, 3, 0, True, _UINT, _NO),  # A.11.2: flag, UINT16
    (21, 3): (_FC, 5, 0, True, _UINT, _NO),  # A.11.3: flag, UINT32, delta
    (21, 4): (_FC, 3, 0, True, _UINT, _NO),  # A.11.4: flag, UINT16, delta
    (21, 5): (_FC, 11, 0, True, _UINT, _ABS),  # A.11.5: flag, UINT32, DNP3TIME
    (21, 6): (_FC, 9, 0, True, _UINT, _ABS),  # A.11.6: flag, UINT16, DNP3TIME
    (21, 7): (_FC, 11, 0, True, _UINT, _ABS),  # A.11.7: flag, UINT32, DNP3TIME, delta
    (21, 8): (_FC, 9, 0, True, _UINT, _ABS),  # A.11.8: flag, UINT16, DNP3TIME, delta
    (21, 9): (_FC, 4, 0, False, _UINT, _NO),  # A.11.9: UINT32
    (21, 10): (_FC, 2, 0, False, _UINT, _NO),  # A.11.10: UINT16
    (21, 11): (_FC, 4, 0, False, _UINT, _NO),  # A.11.11: UINT32, delta
    (21, 12): (_FC, 2, 0, False, _UINT, _NO),  # A.11.12: UINT16, delta
    (22, 1): (_CT, 5, 0, True, _UINT, _NO),  # A.12.1: flag, UINT32
    (22, 2): (_CT, 3, 0, True, _UINT, _NO),  # A.12.2: flag, UINT16
    (22, 3): (_CT, 5, 0, True, _UINT, _NO),  # A.12.3: flag, UINT32, delta
    (22, 4): (_CT, 3, 0, True, _UINT, _NO),  # A.12.4: flag, UINT16, delta
    (22, 5): (_CT, 11, 0, True, _UINT, _ABS),  # A.12.5: flag, UINT32, DNP3TIME
    (22, 6): (_CT, 9, 0, True, _UINT, _ABS),  # A.12.6: flag, UINT16, DNP3TIME
    (22, 7): (_CT, 11, 0, True, _UINT, _ABS),  # A.12.7: flag, UINT32, DNP3TIME, delta
    (22, 8): (_CT, 9, 0, True, _UINT, _ABS),  # A.12.8: flag, UINT16, DNP3TIME, delta
    (23, 1): (_FC, 5, 0, True, _UINT, _NO),  # A.13.1: flag, UINT32
    (23, 2): (_FC, 3, 0, True, _UINT, _NO),  # A.13.2: flag, UINT16
    (23, 3): (_FC, 5, 0, True, _UINT, _NO),  # A.13.3: flag, UINT32, delta (obsolete)
    (23, 4): (_FC, 3, 0, True, _UINT, _NO),  # A.13.4: flag, UINT16, delta (obsolete)
    (23, 5): (_FC, 11, 0, True, _UINT, _ABS),  # A.13.5: flag, UINT32, DNP3TIME
    (23, 6): (_FC, 9, 0, True, _UINT, _ABS),  # A.13.6: flag, UINT16, DNP3TIME
    (23, 7): (_FC, 11, 0, True, _UINT, _ABS),  # A.13.7: flag, UINT32, DNP3TIME, delta (obsolete)
    (23, 8): (_FC, 9, 0, True, _UINT, _ABS),  # A.13.8: flag, UINT16, DNP3TIME, delta (obsolete)
    (30, 1): (_AI, 5, 0, True, _INT, _NO),  # A.14.1: flag, INT32
    (30, 2): (_AI, 3, 0, True, _INT, _NO),  # A.14.2: flag, INT16
    (30, 3): (_AI, 4, 0, False, _INT, _NO),  # A.14.3: INT32
    (30, 4): (_AI, 2, 0, False, _INT, _NO),  # A.14.4: INT16
    (30, 5): (_AI, 5, 0, True, _F32, _NO),  # A.14.5: flag, FLT32
    (30, 6): (_AI, 9, 0, True, _F64, _NO),  # A.14.6: flag, FLT64
    (31, 1): (_FAI, 5, 0, True, _INT, _NO),  # A.15.1: flag, INT32
    (31, 2): (_FAI, 3, 0, True, _INT, _NO),  # A.15.2: flag, INT16
    (31, 3): (_FAI, 11, 0, True, _INT, _ABS),  # A.15.3: flag, INT32, DNP3TIME
    (31, 4): (_FAI, 9, 0, True, _INT, _ABS),  # A.15.4: flag, INT16, DNP3TIME
    (31, 5): (_FAI, 4, 0, False, _INT, _NO),  # A.15.5: INT32
    (31, 6): (_FAI, 2, 0, False, _INT, _NO),  # A.15.6: INT16
    (31, 7): (_FAI, 5, 0, True, _F32, _NO),  # A.15.7: flag, FLT32
    (31, 8): (_FAI, 9, 0, True, _F64, _NO),  # A.15.8: flag, FLT64
    (32, 1): (_AI, 5, 0, True, _INT, _NO),  # A.16.1: flag, INT32
    (32, 2): (_AI, 3, 0, True, _INT, _NO),  # A.16.2: flag, INT16
    (32, 3): (_AI, 11, 0, True, _INT, _ABS),  # A.16.3: flag, INT32, DNP3TIME
    (32, 4): (_AI, 9, 0, True, _INT, _ABS),  # A.16.4: flag, INT16, DNP3TIME
    (32, 5): (_AI, 5, 0, True, _F32, _NO),  # A.16.5: flag, FLT32
    (32, 6): (_AI, 9, 0, True, _F64, _NO),  # A.16.6: flag, FLT64
    (32, 7): (_AI, 11, 0, True, _F32, _ABS),  # A.16.7: flag, FLT32, DNP3TIME
    (32, 8): (_AI, 15, 0, True, _F64, _ABS),  # A.16.8: flag, FLT64, DNP3TIME
    (33, 1): (_FAI, 5, 0, True, _INT, _NO),  # A.17.1: flag, INT32
    (33, 2): (_FAI, 3, 0, True, _INT, _NO),  # A.17.2: flag, INT16
    (33, 3): (_FAI, 11, 0, True, _INT, _ABS),  # A.17.3: flag, INT32, DNP3TIME
    (33, 4): (_FAI, 9, 0, True, _INT, _ABS),  # A.17.4: flag, INT16, DNP3TIME
    (33, 5): (_FAI, 5, 0, True, _F32, _NO),  # A.17.5: flag, FLT32
    (33, 6): (_FAI, 9, 0, True, _F64, _NO),  # A.17.6: flag, FLT64
    (33, 7): (_FAI, 11, 0, True, _F32, _ABS),  # A.17.7: flag, FLT32, DNP3TIME
    (33, 8): (_FAI, 15, 0, True, _F64, _ABS),  # A.17.8: flag, FLT64, DNP3TIME
    (34, 1): (PointKind.ANALOG_DEADBAND, 2, 0, False, _UINT, _NO),  # A.18.1: UINT16
    (34, 2): (PointKind.ANALOG_DEADBAND, 4, 0, False, _UINT, _NO),  # A.18.2: UINT32
    (34, 3): (PointKind.ANALOG_DEADBAND, 4, 0, False, _F32, _NO),  # A.18.3: FLT32
    (40, 1): (_AO, 5, 0, True, _INT, _NO),  # A.19.1: flag, INT32
    (40, 2): (_AO, 3, 0, True, _INT, _NO),  # A.19.2: flag, INT16
    (40, 3): (_AO, 5, 0, True, _F32, _NO),  # A.19.3: flag, FLT32
    (40, 4): (_AO, 9, 0, True, _F64, _NO),  # A.19.4: flag, FLT64
    (41, 1): (PointKind.ANALOG_COMMAND, 5, 0, False, _REC, _NO),  # A.20.1: INT32, status
    (41, 2): (PointKind.ANALOG_COMMAND, 3, 0, False, _REC, _NO),  # A.20.2: INT16, status
    (41, 3): (PointKind.ANALOG_COMMAND, 5, 0, False, _REC, _NO),  # A.20.3: FLT32, status
    (41, 4): (PointKind.ANALOG_COMMAND, 9, 0, False, _REC, _NO),  # A.20.4: FLT64, status
    (42, 1): (_AO, 5, 0, True, _INT, _NO),  # A.21.1: flag, INT32
    (42, 2): (_AO, 3, 0, True, _INT, _NO),  # A.21.2: flag, INT16
    (42, 3): (_AO, 11, 0, True, _INT, _ABS),  # A.21.3: flag, INT32, DNP3TIME
    (42, 4): (_AO, 9, 0, True, _INT, _ABS),  # A.21.4: flag, INT16, DNP3TIME
    (42, 5): (_AO, 5, 0, True, _F32, _NO),  # A.21.5: flag, FLT32
    (42, 6): (_AO, 9, 0, True, _F64, _NO),  # A.21.6: flag, FLT64
    (42, 7): (_AO, 11, 0, True, _F32, _ABS),  # A.21.7: flag, FLT32, DNP3TIME
    (42, 8): (_AO, 15, 0, True, _F64, _ABS),  # A.21.8: flag, FLT64, DNP3TIME
    (43, 1): (PointKind.ANALOG_COMMAND_EVENT, 5, 0, False, _REC, _NO),  # A.22.1: status, INT32
    (43, 2): (PointKind.ANALOG_COMMAND_EVENT, 3, 0, False, _REC, _NO),  # A.22.2: status, INT16
    (43, 3): (PointKind.ANALOG_COMMAND_EVENT, 11, 0, False, _REC, _ABS),  # A.22.3: status, INT32, DNP3TIME
    (43, 4): (PointKind.ANALOG_COMMAND_EVENT, 9, 0, False, _REC, _ABS),  # A.22.4: status, INT16, DNP3TIME
    (43, 5): (PointKind.ANALOG_COMMAND_EVENT, 5, 0, False, _REC, _NO),  # A.22.5: status, FLT32
    (43, 6): (PointKind.ANALOG_COMMAND_EVENT, 9, 0, False, _REC, _NO),  # A.22.6: status, FLT64
    (43, 7): (PointKind.ANALOG_COMMAND_EVENT, 11, 0, False, _REC, _ABS),  # A.22.7: status, FLT32, DNP3TIME
    (43, 8): (PointKind.ANALOG_COMMAND_EVENT, 15, 0, False, _REC, _ABS),  # A.22.8: status, FLT64, DNP3TIME
    (50, 1): (PointKind.TIME, 6, 0, False, _UINT, _NO),  # A.23.1: DNP3TIME
    (51, 1): (PointKind.TIME, 6, 0, False, _UINT, _NO),  # A.24.1: DNP3TIME
    (51, 2): (PointKind.TIME, 6, 0, False, _UINT, _NO),  # A.24.2: DNP3TIME
    (52, 1): (PointKind.TIME_DELAY, 2, 0, False, _UINT, _NO),  # A.25.1: UINT16
    (52, 2): (PointKind.TIME_DELAY, 2, 0, False, _UINT, _NO),  # A.25.2: UINT16
    (60, 1): (PointKind.CLASS, 0, 0, False, ValueCodec.NONE, _NO),  # A.26.1: no object data
    (60, 2): (PointKind.CLASS, 0, 0, False, ValueCodec.NONE, _NO),  # A.26.2
    (60, 3): (PointKind.CLASS, 0, 0, False, ValueCodec.NONE, _NO),  # A.26.3
    (60, 4): (PointKind.CLASS, 0, 0, False, ValueCodec.NONE, _NO),  # A.26.4
    (80, 1): (PointKind.INTERNAL_INDICATION, 0, 1, False, _PK, _NO),  # A.28.1: BSTRn
}


class TestEveryRow:
    """Every field of every row matches its Annex A formal structure."""

    def test_table_holds_exactly_the_expected_pairs(self) -> None:
        assert set(LAYOUTS) == set(_EXPECTED_ROWS)

    @pytest.mark.parametrize("pair", sorted(_EXPECTED_ROWS), ids=lambda p: f"g{p[0]}v{p[1]}")
    def test_row(self, pair: tuple[int, int]) -> None:
        assert layout_for(*pair) == WireLayout(*_EXPECTED_ROWS[pair])


class TestLayoutFields:
    """Field values for representative layouts, read from Annex A."""

    def test_binary_input_packed(self) -> None:
        # A.2.1.2.2: BSTRn, one bit per point, no flags.
        layout = layout_for(1, 1)
        assert layout == WireLayout(PointKind.BINARY_INPUT, 0, 1, False, ValueCodec.PACKED, TimeKind.NONE)
        assert object_width(1, 1) is None

    def test_binary_output_packed(self) -> None:
        # A.6.1.2.2: BSTRn, one bit per point.
        layout = layout_for(10, 1)
        assert layout is not None
        assert (layout.point_kind, layout.bits_per_point, layout.width) == (PointKind.BINARY_OUTPUT, 1, 0)

    def test_double_bit_input_packed(self) -> None:
        # A.4.1.2.2: SET of n UINT2, two bits per point.
        layout = layout_for(3, 1)
        assert layout is not None
        assert (layout.point_kind, layout.bits_per_point, layout.width) == (PointKind.DOUBLE_BIT_INPUT, 2, 0)
        assert layout.is_packed

    def test_binary_input_event_with_time(self) -> None:
        # A.3.2: flag octet then DNP3TIME (UINT48).
        layout = layout_for(2, 2)
        assert layout is not None
        assert layout.has_flags
        assert layout.codec is ValueCodec.FLAG_STATE
        assert layout.time is TimeKind.ABSOLUTE
        assert (layout.width, layout.value_width) == (7, 0)

    def test_binary_input_event_relative_time(self) -> None:
        # A.3.3: flag octet then UINT16 relative time.
        layout = layout_for(2, 3)
        assert layout is not None
        assert (layout.width, layout.time) == (3, TimeKind.RELATIVE)

    def test_analog_float_event_with_time(self) -> None:
        # A.16.7: flag octet, FLT32, DNP3TIME.
        layout = layout_for(32, 7)
        assert layout is not None
        assert (layout.point_kind, layout.codec) == (PointKind.ANALOG_INPUT, ValueCodec.FLOAT32)
        assert (layout.width, layout.value_width, layout.time) == (11, 4, TimeKind.ABSOLUTE)

    def test_analog_input_16_without_flag(self) -> None:
        # A.14.4: INT16 only.
        layout = layout_for(30, 4)
        assert layout is not None
        assert (layout.has_flags, layout.codec, layout.value_width, layout.width) == (False, ValueCodec.INT, 2, 2)

    def test_frozen_counter_with_time_is_not_the_counter_layout(self) -> None:
        # A.11.5: flag octet, UINT32, DNP3TIME; A.10.5 (g20v5) is UINT32 alone.
        frozen = layout_for(21, 5)
        counter = layout_for(20, 5)
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
        assert layout_for(30, 99) is None
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

    def test_packed_layout_with_time_is_refused(self) -> None:
        with pytest.raises(ValueError, match="packed"):
            WireLayout(PointKind.BINARY_INPUT, 0, 1, False, ValueCodec.PACKED, TimeKind.ABSOLUTE)

    def test_negative_bits_per_point_is_refused(self) -> None:
        with pytest.raises(ValueError, match="bits per point"):
            WireLayout(PointKind.BINARY_INPUT, 0, -1, False, ValueCodec.PACKED, TimeKind.NONE)

    def test_width_smaller_than_flags_and_time_is_refused(self) -> None:
        with pytest.raises(ValueError, match="width"):
            WireLayout(PointKind.ANALOG_INPUT, 6, 0, True, ValueCodec.INT, TimeKind.ABSOLUTE)


def _layout(group: int, variation: int) -> WireLayout:
    layout = layout_for(group, variation)
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
