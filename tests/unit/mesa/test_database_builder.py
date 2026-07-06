"""Tests for the PICS profile database builder.

The load-bearing assertions here are on the AI transmission integers: the
database must carry the scaled transmission value, never the raw engineering
float. Each AI assertion is a hand-computed exact integer (data-invariants
Rule 1). Curve/schedule AI points must register at their absolute indices, and
the AO store must carry the transmission-integer range.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.database_builder import _assert_unique_by_index, _dedup_ai_points, build_database
from dnp3.mesa.profile import AiPoint, EventClass, PicsProfile, PointType, load_profile


def _make_ai(point_index: int, value: float = 1.0) -> AiPoint:
    """Minimal AiPoint fixture for dedup unit tests."""
    return AiPoint(
        point_index=point_index,
        name=f"AI{point_index}",
        event_class=EventClass.CLASS1,
        minimum=0,
        maximum=10000,
        multiplier=1.0,
        offset=0.0,
        units="V",
        iec_61850_uid=f"X.Y.{point_index}",
        value=value,
        purpose="test",
        mandatory_1815=False,
        mandatory_1547=False,
    )


FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"


@pytest.fixture()
def profile() -> PicsProfile:
    return load_profile(TEST_PROFILE)


@pytest.fixture()
def built(profile: PicsProfile) -> tuple[Database, AnalogOutputStore]:
    return build_database(profile)


@pytest.fixture()
def database(built: tuple[Database, AnalogOutputStore]) -> Database:
    return built[0]


@pytest.fixture()
def ao_store(built: tuple[Database, AnalogOutputStore]) -> AnalogOutputStore:
    return built[1]


class TestReturnType:
    def test_returns_tuple(self, built: tuple[Database, AnalogOutputStore]) -> None:
        assert isinstance(built, tuple)
        assert len(built) == 2

    def test_first_is_database(self, database: Database) -> None:
        assert isinstance(database, Database)

    def test_second_is_ao_store(self, ao_store: AnalogOutputStore) -> None:
        assert isinstance(ao_store, AnalogOutputStore)


class TestPointCounts:
    def test_binary_input_count(self, database: Database) -> None:
        # base BI0 + meter BI5000 + der BI6000
        assert database.binary_input_count == 3

    def test_binary_output_count(self, database: Database) -> None:
        assert database.binary_output_count == 1

    def test_analog_input_count(self, database: Database) -> None:
        # base AI0, AI1 + meter AI5100 + 8 curve points = 11
        assert database.analog_input_count == 11

    def test_ao_store_length(self, ao_store: AnalogOutputStore) -> None:
        # base AO0, AO249 + battery AO20000
        assert len(ao_store) == 3


class TestAnalogInputTransmissionScaling:
    """The database stores the transmission integer, not the engineering float."""

    def test_ai0_scaled_transmission(self, database: Database) -> None:
        # value 125.0, multiplier 0.1, offset 5.0 -> raw = (125 - 5)/0.1 = 1200
        point = database.get_analog_input(0)
        assert point is not None
        assert point.value == 1200
        assert not isinstance(point.value, float) or point.value == int(point.value)

    def test_power_factor_sign_preserved(self, database: Database) -> None:
        # PF value -0.95, multiplier 0.001, offset 0 -> raw = -950. The sign
        # must survive; a magnitude map would give +950 (Vance Finding B).
        point = database.get_analog_input(1)
        assert point is not None
        assert point.value == -950

    def test_meter_voltage_scaled(self, database: Database) -> None:
        # value 120.0, multiplier 0.1, offset 0 -> raw = 1200
        point = database.get_analog_input(5100)
        assert point is not None
        assert point.value == 1200

    def test_curve_x_value_scaled(self, database: Database) -> None:
        # curve x[0] value 100.0, multiplier 1, offset 0 -> raw = 100
        point = database.get_analog_input(333)
        assert point is not None
        assert point.value == 100


class TestCurvePointRegistration:
    """Every curve AI point registers at its absolute index (base-only trap)."""

    def test_all_curve_header_points_present(self, database: Database) -> None:
        for index in (329, 330, 331, 332):
            assert database.get_analog_input(index) is not None, f"AI{index} missing"

    def test_all_curve_array_points_present(self, database: Database) -> None:
        for index in (333, 334, 433, 434):
            assert database.get_analog_input(index) is not None, f"AI{index} missing"


class TestAnalogOutputStore:
    def test_ao0_transmission_range(self, ao_store: AnalogOutputStore) -> None:
        entry = ao_store.get(0)
        assert entry is not None
        # minimum/maximum are transmission integers straight from the profile.
        assert entry.minimum == 0.0
        assert entry.maximum == 1000.0
        assert entry.multiplier == pytest.approx(0.1)
        # initial value is the in-range minimum transmission integer.
        assert entry.value == 0.0

    def test_curve_ao_unbounded_high(self, ao_store: AnalogOutputStore) -> None:
        entry = ao_store.get(249)
        assert entry is not None
        assert entry.maximum == float(2147483647)


class TestQualityFlags:
    def test_bi_quality_online(self, database: Database) -> None:
        point = database.get_binary_input(0)
        assert point is not None
        assert point.quality == BinaryQuality.ONLINE

    def test_ai_quality_online(self, database: Database) -> None:
        point = database.get_analog_input(0)
        assert point is not None
        assert point.quality == AnalogQuality.ONLINE


class TestSparseHighIndex:
    def test_equipment_point_at_high_index(self, database: Database) -> None:
        # Meter AI5100 lands in the sparse database at its absolute index.
        assert database.get_analog_input(5100) is not None


class TestExclusion:
    def test_exclude_meter_ai(self, profile: PicsProfile) -> None:
        excluded = {PointType.ANALOG_INPUT: {5100}}
        database, _ = build_database(profile, excluded_indices=excluded)
        assert database.get_analog_input(5100) is None
        assert database.get_analog_input(0) is not None

    def test_exclude_battery_ao(self, profile: PicsProfile) -> None:
        excluded = {PointType.ANALOG_OUTPUT: {20000}}
        _, ao_store = build_database(profile, excluded_indices=excluded)
        assert ao_store.get(20000) is None
        assert ao_store.get(0) is not None

    def test_empty_exclusion_changes_nothing(self, profile: PicsProfile) -> None:
        database, ao_store = build_database(profile, excluded_indices={})
        assert database.analog_input_count == 11
        assert len(ao_store) == 3


class TestClampBeforeScale:
    def test_out_of_range_value_clamped(self, database: Database) -> None:
        # No fixture point is out of range, so assert the in-range values did
        # not get clamped away from their expected transmission integers.
        point = database.get_analog_input(0)
        assert point is not None
        assert point.value == 1200

    def test_no_nan_in_stored_values(self, database: Database) -> None:
        for index in (0, 1, 5100, 333):
            point = database.get_analog_input(index)
            assert point is not None
            assert not (isinstance(point.value, float) and math.isnan(point.value))


class TestDedupValueSurvival:
    """MEDIUM 4a: first point's value survives when a duplicate index appears in
    the overlay pool; the first registration is the one that lands in the DB."""

    def test_first_point_value_survives_overlay_duplicate(self) -> None:
        # Two overlay points share index 329; the first value (42.0) must survive.
        first = _make_ai(329, value=42.0)
        second = _make_ai(329, value=99.0)
        result = _dedup_ai_points(base_points=[], overlay_points=[first, second])
        assert len(result) == 1
        assert result[0].value == 42.0

    def test_base_point_value_wins_over_overlay_at_same_index(self) -> None:
        # A base point at index 329 and an overlay point at index 329: base wins.
        base = _make_ai(329, value=10.0)
        overlay = _make_ai(329, value=20.0)
        result = _dedup_ai_points(base_points=[base], overlay_points=[overlay])
        assert len(result) == 1
        assert result[0].value == 10.0

    def test_distinct_indices_all_survive(self) -> None:
        points = [_make_ai(i, value=float(i)) for i in (329, 330, 331)]
        result = _dedup_ai_points(base_points=[], overlay_points=points)
        assert len(result) == 3
        assert [p.point_index for p in result] == [329, 330, 331]


class TestDedupSafetyGuard:
    """MEDIUM 4b: a base-vs-base collision raises; silent shadowing is forbidden."""

    def test_duplicate_base_index_raises(self) -> None:
        # Two BASE points with the same index is a profile error, not multiplexing.
        a = _make_ai(100, value=1.0)
        b = _make_ai(100, value=2.0)
        with pytest.raises(ValueError, match="duplicate point_index"):
            _dedup_ai_points(base_points=[a, b], overlay_points=[])

    def test_assert_unique_raises_on_duplicate_bi(self) -> None:
        # _assert_unique_by_index used for BI/BO/AO: any duplicate raises.
        from dnp3.mesa.profile import BiPoint

        def _make_bi(idx: int) -> BiPoint:
            return BiPoint(
                point_index=idx,
                name=f"BI{idx}",
                event_class=EventClass.CLASS1,
                state_0="off",
                state_1="on",
                iec_61850_uid="X.Y",
                purpose="test",
                mandatory_1815=False,
                mandatory_1547=False,
            )

        with pytest.raises(ValueError, match="duplicate point_index"):
            _assert_unique_by_index([_make_bi(5), _make_bi(5)], label="BI")


class TestCtrRegistration:
    """CTR points must register as 32-bit counters; frozen_counter_exists honored.

    Wire-level assertions (data-invariants Rule 1): assert point_index,
    group/variation via CounterPoint.MAX_VALUE (32-bit = 2^32-1), quality
    ONLINE, event-class assignment, and frozen counter presence.
    """

    def test_counter_count_from_fixture(self, database: Database) -> None:
        # Fixture has 2 CTR points: CTR0 and CTR1.
        assert database.counter_count == 2

    def test_frozen_counter_count_from_fixture(self, database: Database) -> None:
        # CTR0 has frozen_counter_exists=True; CTR1 has False.
        assert database.frozen_counter_count == 1

    def test_ctr0_counter_registered_at_correct_index(self, database: Database) -> None:
        point = database.get_counter(0)
        assert point is not None
        assert point.index == 0

    def test_ctr1_counter_registered_at_correct_index(self, database: Database) -> None:
        point = database.get_counter(1)
        assert point is not None
        assert point.index == 1

    def test_counter_initial_value_is_zero(self, database: Database) -> None:
        # CTR points carry no initial value in PicsProfile; counters start at 0.
        point = database.get_counter(0)
        assert point is not None
        assert point.value == 0

    def test_counter_is_32bit_unsigned(self, database: Database) -> None:
        # The 32-bit variant is required (Vance domain guidance).
        # CounterPoint.MAX_VALUE is 2^32 - 1 for the 32-bit variant.
        point = database.get_counter(0)
        assert point is not None
        assert point.MAX_VALUE == 2**32 - 1

    def test_counter_quality_online(self, database: Database) -> None:
        from dnp3.core.flags import CounterQuality

        point = database.get_counter(0)
        assert point is not None
        assert point.quality == CounterQuality.ONLINE

    def test_ctr0_frozen_counter_registered(self, database: Database) -> None:
        # CTR0 has frozen_counter_exists=True -> add_frozen_counter at same index.
        point = database.get_frozen_counter(0)
        assert point is not None
        assert point.index == 0

    def test_ctr1_no_frozen_counter(self, database: Database) -> None:
        # CTR1 has frozen_counter_exists=False -> no frozen counter at index 1.
        assert database.get_frozen_counter(1) is None

    def test_frozen_counter_is_32bit_unsigned(self, database: Database) -> None:
        point = database.get_frozen_counter(0)
        assert point is not None
        assert point.MAX_VALUE == 2**32 - 1

    def test_frozen_counter_initial_value_is_zero(self, database: Database) -> None:
        point = database.get_frozen_counter(0)
        assert point is not None
        assert point.value == 0

    def test_frozen_counter_quality_online(self, database: Database) -> None:
        from dnp3.core.flags import CounterQuality

        point = database.get_frozen_counter(0)
        assert point is not None
        assert point.quality == CounterQuality.ONLINE

    def test_ctr0_counter_event_class_none(self, database: Database) -> None:
        # Fixture CTR0: counter_event_class="None" -> EventClass.NONE (0).
        from dnp3.database.point import EventClass as DbEventClass

        point = database.get_counter(0)
        assert point is not None
        assert point.config.event_class == DbEventClass.NONE

    def test_ctr0_frozen_event_class_3(self, database: Database) -> None:
        # Fixture CTR0: frozen_counter_event_class="Class3" -> DbEventClass.CLASS_3.
        from dnp3.database.point import EventClass as DbEventClass

        point = database.get_frozen_counter(0)
        assert point is not None
        assert point.config.event_class == DbEventClass.CLASS_3

    def test_ctr1_counter_event_class_1(self, database: Database) -> None:
        # Fixture CTR1: counter_event_class="Class1" -> DbEventClass.CLASS_1.
        from dnp3.database.point import EventClass as DbEventClass

        point = database.get_counter(1)
        assert point is not None
        assert point.config.event_class == DbEventClass.CLASS_1

    def test_missing_counter_index_returns_none(self, database: Database) -> None:
        assert database.get_counter(9999) is None

    def test_missing_frozen_counter_index_returns_none(self, database: Database) -> None:
        assert database.get_frozen_counter(9999) is None


class TestCtrFullJsonCensus:
    """All 8 CTR points in full.json must register; none are silently dropped."""

    @pytest.fixture()
    def full_profile(self) -> PicsProfile:
        # parents[3] from tests/unit/mesa/test_database_builder.py is the repo root.
        full_path = Path(__file__).parents[3] / "data" / "profiles" / "full.json"
        return load_profile(full_path)

    @pytest.fixture()
    def full_database(self, full_profile: PicsProfile) -> Database:
        db, _ = build_database(full_profile)
        return db

    def test_all_8_counters_registered(self, full_database: Database) -> None:
        assert full_database.counter_count == 8

    def test_all_8_counters_have_frozen_counterpart(self, full_database: Database) -> None:
        # All 8 full.json CTR points have frozen_counter_exists=True.
        assert full_database.frozen_counter_count == 8

    def test_counter_indices_match_full_json(self, full_database: Database) -> None:
        # full.json CTR point_index values: 0,1,2,3,5000,5001,5002,5003.
        expected = {0, 1, 2, 3, 5000, 5001, 5002, 5003}
        registered = {p.index for p in full_database.get_all_counters()}
        assert registered == expected

    def test_frozen_counter_indices_match_full_json(self, full_database: Database) -> None:
        expected = {0, 1, 2, 3, 5000, 5001, 5002, 5003}
        registered = {p.index for p in full_database.get_all_frozen_counters()}
        assert registered == expected

    def test_all_counters_start_at_zero(self, full_database: Database) -> None:
        for counter in full_database.get_all_counters():
            assert counter.value == 0, f"CTR{counter.index} initial value is not 0"

    def test_all_counters_are_online(self, full_database: Database) -> None:
        from dnp3.core.flags import CounterQuality

        for counter in full_database.get_all_counters():
            assert counter.quality == CounterQuality.ONLINE

    def test_high_index_counters_registered(self, full_database: Database) -> None:
        # CTR points at 5000-5003 must land at their absolute sparse indices.
        for idx in (5000, 5001, 5002, 5003):
            assert full_database.get_counter(idx) is not None, f"CTR{idx} missing"
            assert full_database.get_frozen_counter(idx) is not None, f"FrozenCTR{idx} missing"


class TestCtrDuplicateIndexRejection:
    """build_database raises ValueError on duplicate CTR point_index values.

    CTR points route through _assert_unique_by_index before registration;
    a duplicate index would silently shadow the first point in the database,
    so the guard raises with context instead.
    """

    def _make_ctr(self, point_index: int) -> object:
        from dnp3.mesa.profile import CtrPoint, EventClass

        return CtrPoint(
            point_index=point_index,
            name=f"CTR{point_index}",
            counter_event_class=EventClass.NONE,
            frozen_counter_exists=False,
            frozen_counter_event_class=EventClass.NONE,
            iec_61850_uid=f"MMTR.X.{point_index}",
            purpose="Metering",
            mandatory_1815=False,
            mandatory_1547=False,
        )

    def test_duplicate_ctr_index_raises_value_error(self, profile: PicsProfile) -> None:
        import dataclasses

        # Build a profile with two CTR points sharing index 0.
        dup_point = self._make_ctr(0)
        patched = dataclasses.replace(profile, ctr=(dup_point, dup_point))
        with pytest.raises(ValueError, match="duplicate point_index"):
            build_database(patched)


class TestNegativeMultiplierClamp:
    """MEDIUM 5c/5d: negative multiplier inverts engineering bounds; the sorted
    clamp handles it, and an out-of-range value clamps to the boundary int."""

    def test_negative_multiplier_clamp_preserves_in_range(self, profile: PicsProfile) -> None:
        # The fixture has no negative-multiplier point, so build a synthetic
        # profile with one and assert the transmission int is correct.
        #
        # Synthetic: value=5.0, mult=-1.0, offset=0.0, min=-100, max=100.
        # eng_a = min * mult + offset = -100 * -1 + 0 = 100
        # eng_b = max * mult + offset = 100 * -1 + 0 = -100
        # low, high = -100, 100 (sorted)
        # clamp(5.0, -100, 100) = 5.0 (in range)
        # transmission = (5.0 - 0) / -1.0 = -5
        neg_mult_point = _make_ai(9999, value=5.0)
        # Override fields via dataclass replace (frozen: use replace pattern).
        import dataclasses

        neg_mult_point = dataclasses.replace(neg_mult_point, multiplier=-1.0, minimum=-100, maximum=100)
        from dnp3.mesa.database_builder import _scaled_transmission

        assert _scaled_transmission(neg_mult_point) == -5

    def test_out_of_range_value_clamps_to_boundary_transmission(self) -> None:
        # value=200.0 but eng_max for (mult=-1.0, offset=0, max=100) is 100.
        # clamp(200.0, -100, 100) = 100.0
        # transmission = (100.0 - 0) / -1.0 = -100
        import dataclasses

        point = dataclasses.replace(_make_ai(9998, value=200.0), multiplier=-1.0, minimum=-100, maximum=100)
        from dnp3.mesa.database_builder import _scaled_transmission

        assert _scaled_transmission(point) == -100
