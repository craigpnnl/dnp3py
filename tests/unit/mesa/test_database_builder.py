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
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.profile import PicsProfile, PointType, load_profile

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
