"""Tests for the MESA database builder module.

RED phase: These tests define the expected API for
dnp3.mesa.database_builder.build_database before implementation exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.profile import PointType, load_profile

# ---------------------------------------------------------------------------
# Fixture path helper
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"


@pytest.fixture()
def profile():
    """Load the test profile once for all tests."""
    return load_profile(TEST_PROFILE)


@pytest.fixture()
def built(profile):
    """Build database and AO store from profile."""
    return build_database(profile)


@pytest.fixture()
def database(built):
    return built[0]


@pytest.fixture()
def ao_store(built):
    return built[1]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_tuple(self, built):
        assert isinstance(built, tuple)
        assert len(built) == 2

    def test_first_element_is_database(self, database):
        assert isinstance(database, Database)

    def test_second_element_is_ao_store(self, ao_store):
        assert isinstance(ao_store, AnalogOutputStore)


# ---------------------------------------------------------------------------
# Point counts
# ---------------------------------------------------------------------------


class TestPointCounts:
    def test_binary_input_count(self, database):
        assert database.binary_input_count == 2  # BI0, BI5000

    def test_binary_output_count(self, database):
        assert database.binary_output_count == 1  # BO0 only; BO1 unsupported

    def test_analog_input_count(self, database):
        assert database.analog_input_count == 2  # AI0, AI5000

    def test_ao_store_length(self, ao_store):
        assert len(ao_store) == 2  # AO0, AO20000


# ---------------------------------------------------------------------------
# Binary input values
# ---------------------------------------------------------------------------


class TestBinaryInputValues:
    def test_bi0_value(self, database):
        point = database.get_binary_input(0)
        assert point is not None
        assert point.value is True  # profile value=1

    def test_bi5000_value(self, database):
        point = database.get_binary_input(5000)
        assert point is not None
        assert point.value is True  # profile value=1


# ---------------------------------------------------------------------------
# Binary output values
# ---------------------------------------------------------------------------


class TestBinaryOutputValues:
    def test_bo0_value(self, database):
        point = database.get_binary_output(0)
        assert point is not None
        assert point.value is True  # profile value=1


# ---------------------------------------------------------------------------
# Analog input values
# ---------------------------------------------------------------------------


class TestAnalogInputValues:
    def test_ai0_value(self, database):
        point = database.get_analog_input(0)
        assert point is not None
        assert point.value == 0.0  # profile value=0

    def test_ai5000_value(self, database):
        point = database.get_analog_input(5000)
        assert point is not None
        assert point.value == 120.0  # profile value=120


# ---------------------------------------------------------------------------
# Analog output store values
# ---------------------------------------------------------------------------


class TestAnalogOutputStoreValues:
    def test_ao0_entry(self, ao_store):
        entry = ao_store.get(0)
        assert entry is not None
        assert entry.value == 100.0
        assert entry.minimum == 0
        assert entry.maximum == 100
        assert entry.multiplier == 0.1
        assert entry.units == "percent"

    def test_ao20000_entry(self, ao_store):
        entry = ao_store.get(20000)
        assert entry is not None
        assert entry.value == 50.0
        assert entry.minimum == 0
        assert entry.maximum == 100
        assert entry.units == "percent"


# ---------------------------------------------------------------------------
# Quality flags — must be ONLINE, not RESTART
# ---------------------------------------------------------------------------


class TestQualityFlags:
    def test_binary_input_quality_online(self, database):
        point = database.get_binary_input(0)
        assert point is not None
        assert point.quality == BinaryQuality.ONLINE

    def test_binary_output_quality_online(self, database):
        point = database.get_binary_output(0)
        assert point is not None
        assert point.quality == BinaryQuality.ONLINE

    def test_analog_input_quality_online(self, database):
        point = database.get_analog_input(0)
        assert point is not None
        assert point.quality == AnalogQuality.ONLINE


# ---------------------------------------------------------------------------
# Nonexistent index returns None
# ---------------------------------------------------------------------------


class TestNonexistentIndex:
    def test_binary_input_missing(self, database):
        assert database.get_binary_input(9999) is None

    def test_binary_output_missing(self, database):
        assert database.get_binary_output(9999) is None

    def test_analog_input_missing(self, database):
        assert database.get_analog_input(9999) is None


# ---------------------------------------------------------------------------
# Exclusion support
# ---------------------------------------------------------------------------


class TestBuildDatabaseWithExclusion:
    """Tests for build_database with excluded_indices parameter."""

    def test_exclude_meter_points_drops_bi(self, profile):
        """Excluding meter BI5000 should reduce binary input count by 1."""
        excluded = {PointType.BINARY_INPUT: {5000}}
        database, _ = build_database(profile, excluded_indices=excluded)

        assert database.binary_input_count == 1  # only BI0 remains
        assert database.get_binary_input(0) is not None
        assert database.get_binary_input(5000) is None

    def test_exclude_meter_points_drops_ai(self, profile):
        """Excluding meter AI5000 should reduce analog input count by 1."""
        excluded = {PointType.ANALOG_INPUT: {5000}}
        database, _ = build_database(profile, excluded_indices=excluded)

        assert database.analog_input_count == 1  # only AI0 remains
        assert database.get_analog_input(0) is not None
        assert database.get_analog_input(5000) is None

    def test_exclude_battery_points_drops_ao(self, profile):
        """Excluding battery AO20000 should reduce AO store length by 1."""
        excluded = {PointType.ANALOG_OUTPUT: {20000}}
        _, ao_store = build_database(profile, excluded_indices=excluded)

        assert len(ao_store) == 1  # only AO0 remains
        assert ao_store.get(0) is not None
        assert ao_store.get(20000) is None

    def test_exclude_multiple_point_types(self, profile):
        """Excluding across multiple point types works together."""
        excluded = {
            PointType.BINARY_INPUT: {5000},
            PointType.ANALOG_INPUT: {5000},
            PointType.ANALOG_OUTPUT: {20000},
        }
        database, ao_store = build_database(profile, excluded_indices=excluded)

        assert database.binary_input_count == 1
        assert database.analog_input_count == 1
        assert len(ao_store) == 1

    def test_empty_exclusion_dict_changes_nothing(self, profile):
        """An empty exclusion dict should behave like no exclusion."""
        database, ao_store = build_database(profile, excluded_indices={})

        assert database.binary_input_count == 2
        assert database.analog_input_count == 2
        assert len(ao_store) == 2
