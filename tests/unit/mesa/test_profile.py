"""RED phase tests for the MESA profile loader module.

These tests define the expected API for dnp3.mesa.profile before
implementation exists.  Every test here MUST fail until the module
is written (GREEN phase).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.mesa.profile import (
    PointType,
    Profile,
    ProfilePoint,
    ProfileSection,
    load_profile,
    parse_index,
)

# ---------------------------------------------------------------------------
# Fixture path helper
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"


# ===========================================================================
# parse_index
# ===========================================================================


class TestParseIndex:
    """Validate that parse_index converts string indices like 'BO0' into
    a (PointType, int) tuple."""

    def test_binary_output_zero(self) -> None:
        point_type, number = parse_index("BO0")
        assert point_type is PointType.BINARY_OUTPUT
        assert number == 0

    def test_binary_input_5000(self) -> None:
        point_type, number = parse_index("BI5000")
        assert point_type is PointType.BINARY_INPUT
        assert number == 5000

    def test_analog_output_20000(self) -> None:
        point_type, number = parse_index("AO20000")
        assert point_type is PointType.ANALOG_OUTPUT
        assert number == 20000

    def test_analog_input_zero(self) -> None:
        point_type, number = parse_index("AI0")
        assert point_type is PointType.ANALOG_INPUT
        assert number == 0

    def test_invalid_prefix_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            parse_index("XX0")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_index("")

    def test_prefix_without_number_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            parse_index("BO")


# ===========================================================================
# ProfilePoint
# ===========================================================================


class TestProfilePoint:
    """Verify ProfilePoint dataclass construction with full and minimal fields."""

    def test_construction_all_fields(self) -> None:
        point = ProfilePoint(
            index=0,
            point_type=PointType.ANALOG_OUTPUT,
            description="Active Power Setpoint",
            uid="DWMX.WMaxPct",
            purpose="Limit",
            value=100,
            supported=True,
            associated_index="AI0",
            minimum=0,
            maximum=100,
            multiplier=0.1,
            offset=0,
            units="percent",
            entity_number=None,
            entity_type=None,
            entity_index_offset=None,
            event_class=None,
        )
        assert point.index == 0
        assert point.point_type is PointType.ANALOG_OUTPUT
        assert point.description == "Active Power Setpoint"
        assert point.uid == "DWMX.WMaxPct"
        assert point.purpose == "Limit"
        assert point.value == 100
        assert point.supported is True
        assert point.associated_index == "AI0"
        assert point.minimum == 0
        assert point.maximum == 100
        assert point.multiplier == pytest.approx(0.1)
        assert point.offset == 0
        assert point.units == "percent"

    def test_construction_minimal_fields(self) -> None:
        """Minimal construction: only required fields, rest default to None."""
        point = ProfilePoint(
            index=5,
            point_type=PointType.BINARY_INPUT,
            description="Minimal point",
            uid="TEST.minimal",
            purpose="Test",
            value=0,
            supported=True,
        )
        assert point.index == 5
        assert point.point_type is PointType.BINARY_INPUT
        assert point.value == 0
        assert point.supported is True
        # Optional fields should default to None
        assert point.associated_index is None
        assert point.minimum is None
        assert point.maximum is None
        assert point.multiplier is None
        assert point.offset is None
        assert point.units is None
        assert point.entity_number is None
        assert point.entity_type is None
        assert point.entity_index_offset is None
        assert point.event_class is None

    def test_entity_fields_present(self) -> None:
        point = ProfilePoint(
            index=5000,
            point_type=PointType.BINARY_INPUT,
            description="Meter 1 Online",
            uid="MMTR.Online",
            purpose="Monitoring",
            value=1,
            supported=True,
            entity_number=1,
            entity_type="Meter",
            entity_index_offset=0,
        )
        assert point.entity_number == 1
        assert point.entity_type == "Meter"
        assert point.entity_index_offset == 0

    def test_analog_fields_present(self) -> None:
        point = ProfilePoint(
            index=0,
            point_type=PointType.ANALOG_INPUT,
            description="Active Power",
            uid="DWMX.WMaxPct.val",
            purpose="Monitoring",
            value=0,
            supported=True,
            minimum=0,
            maximum=1000,
            multiplier=0.1,
            offset=0,
            units="watts",
            event_class=1,
        )
        assert point.minimum == 0
        assert point.maximum == 1000
        assert point.multiplier == pytest.approx(0.1)
        assert point.offset == 0
        assert point.units == "watts"
        assert point.event_class == 1


# ===========================================================================
# load_profile  (integration-style unit tests using fixture JSON)
# ===========================================================================


class TestLoadProfile:
    """Verify that load_profile reads a JSON file and returns a populated
    Profile instance with correctly parsed sections and points."""

    @pytest.fixture()
    def profile(self) -> Profile:
        return load_profile(TEST_PROFILE)

    # -- basic loading --

    def test_returns_profile_instance(self, profile: Profile) -> None:
        assert isinstance(profile, Profile)

    def test_entities_match_fixture(self, profile: Profile) -> None:
        assert profile.entities == {"meters": 1, "ders": 0, "inverters": 0, "batteries": 1}

    # -- section point counts --

    def test_binary_outputs_filters_unsupported(self, profile: Profile) -> None:
        """BO1 is unsupported and must be excluded."""
        assert len(profile.binary_outputs.points) == 1

    def test_binary_inputs_count(self, profile: Profile) -> None:
        assert len(profile.binary_inputs.points) == 2

    def test_analog_outputs_count(self, profile: Profile) -> None:
        assert len(profile.analog_outputs.points) == 3  # AO0, AO20000, AO249

    def test_analog_inputs_count(self, profile: Profile) -> None:
        assert len(profile.analog_inputs.points) == 2

    # -- unsupported filtering --

    def test_unsupported_point_excluded(self, profile: Profile) -> None:
        """BO1 (supported=false) must not appear anywhere in binary_outputs."""
        uids = [p.uid for p in profile.binary_outputs.points]
        assert "TEST.unsupported" not in uids

    # -- parsed index values --

    def test_binary_output_parsed_index(self, profile: Profile) -> None:
        bo0 = profile.binary_outputs.points[0]
        assert bo0.index == 0
        assert bo0.point_type is PointType.BINARY_OUTPUT

    def test_binary_input_parsed_index(self, profile: Profile) -> None:
        bi5000 = [p for p in profile.binary_inputs.points if p.index == 5000]
        assert len(bi5000) == 1
        assert bi5000[0].point_type is PointType.BINARY_INPUT

    def test_analog_output_parsed_index(self, profile: Profile) -> None:
        ao20000 = [p for p in profile.analog_outputs.points if p.index == 20000]
        assert len(ao20000) == 1
        assert ao20000[0].point_type is PointType.ANALOG_OUTPUT

    def test_analog_input_parsed_index(self, profile: Profile) -> None:
        ai0 = profile.analog_inputs.points[0]
        assert ai0.index == 0
        assert ai0.point_type is PointType.ANALOG_INPUT

    # -- field values from fixture --

    def test_binary_output_values(self, profile: Profile) -> None:
        bo0 = profile.binary_outputs.points[0]
        assert bo0.description == "System Set Lockout State"
        assert bo0.uid == "DSTO.DEROpSt.disconnected_and_blocked"
        assert bo0.purpose == "State"
        assert bo0.value == 1
        assert bo0.supported is True

    def test_analog_output_values(self, profile: Profile) -> None:
        ao0 = next(p for p in profile.analog_outputs.points if p.index == 0)
        assert ao0.description == "Active Power Setpoint"
        assert ao0.value == 100
        assert ao0.minimum == 0
        assert ao0.maximum == 100
        assert ao0.multiplier == pytest.approx(0.1)
        assert ao0.units == "percent"

    # -- entity fields --

    def test_entity_point_fields(self, profile: Profile) -> None:
        bi5000 = next(p for p in profile.binary_inputs.points if p.index == 5000)
        assert bi5000.entity_number == 1
        assert bi5000.entity_type == "Meter"
        assert bi5000.entity_index_offset == 0

    def test_battery_entity_fields(self, profile: Profile) -> None:
        ao20000 = next(p for p in profile.analog_outputs.points if p.index == 20000)
        assert ao20000.entity_number == 1
        assert ao20000.entity_type == "Battery"
        assert ao20000.entity_index_offset == 0

    # -- analog fields --

    def test_analog_input_fields(self, profile: Profile) -> None:
        ai0 = profile.analog_inputs.points[0]
        assert ai0.minimum == 0
        assert ai0.maximum == 1000
        assert ai0.multiplier == pytest.approx(0.1)
        assert ai0.offset == 0
        assert ai0.units == "watts"
        assert ai0.event_class == 1

    def test_analog_input_entity_with_event_class(self, profile: Profile) -> None:
        ai5000 = next(p for p in profile.analog_inputs.points if p.index == 5000)
        assert ai5000.entity_number == 1
        assert ai5000.entity_type == "Meter"
        assert ai5000.event_class == 2

    # -- section offsets --

    def test_binary_outputs_offsets(self, profile: Profile) -> None:
        assert isinstance(profile.binary_outputs, ProfileSection)
        assert profile.binary_outputs.offsets == {
            "scada": 0,
            "historical_meters": 5000,
            "historical_batteries": 20000,
        }

    def test_analog_inputs_offsets(self, profile: Profile) -> None:
        assert profile.analog_inputs.offsets == {
            "scada": 0,
            "historical_meters": 5000,
            "historical_batteries": 20000,
        }

    # -- error handling --

    def test_nonexistent_file_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_profile(Path("/tmp/nonexistent_profile_abc123.json"))
