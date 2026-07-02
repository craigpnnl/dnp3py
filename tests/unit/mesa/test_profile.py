"""Tests for the PICS profile model and loader.

Covers parsing the mesa-tool PicsProfile shape into dnp3py's dataclass twin:
per-type points, event-class mapping, verbatim UID, equipment flattening, curve
registration, CTR parsing, and loud failure on unknown enums or missing fields.
The real bundled ``full.json`` is parsed as a golden fixture so a mesa-tool
schema change breaks dnp3py loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnp3.mesa.profile import (
    AiPoint,
    AoPoint,
    BiPoint,
    BoPoint,
    CtrPoint,
    EventClass,
    PicsProfile,
    PointType,
    load_profile,
    parse_assoc_index,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"

# Bundled full profile: the golden-parse census target.
BUNDLED_PROFILES = Path(__file__).parents[3] / "data" / "profiles"
FULL_PROFILE = BUNDLED_PROFILES / "full.json"


# ===========================================================================
# EventClass mapping
# ===========================================================================


class TestEventClass:
    def test_from_profile_string(self) -> None:
        assert EventClass.from_profile_string("Class1") is EventClass.CLASS1
        assert EventClass.from_profile_string("Class2") is EventClass.CLASS2
        assert EventClass.from_profile_string("Class3") is EventClass.CLASS3
        assert EventClass.from_profile_string("None") is EventClass.NONE

    def test_unknown_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown event_class"):
            EventClass.from_profile_string("Class4")

    def test_to_dnp3_class_mapping(self) -> None:
        assert EventClass.CLASS1.to_dnp3_class() == 1
        assert EventClass.CLASS2.to_dnp3_class() == 2
        assert EventClass.CLASS3.to_dnp3_class() == 3
        assert EventClass.NONE.to_dnp3_class() == 0


# ===========================================================================
# parse_assoc_index
# ===========================================================================


class TestParseAssocIndex:
    def test_analog_input(self) -> None:
        pt, idx = parse_assoc_index("AI29")
        assert pt is PointType.ANALOG_INPUT
        assert idx == 29

    def test_binary_input(self) -> None:
        pt, idx = parse_assoc_index("BI11")
        assert pt is PointType.BINARY_INPUT
        assert idx == 11

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid association index"):
            parse_assoc_index("XX0")


# ===========================================================================
# load_profile on the small fixture
# ===========================================================================


class TestLoadFixture:
    @pytest.fixture()
    def profile(self) -> PicsProfile:
        return load_profile(TEST_PROFILE)

    def test_returns_pics_profile(self, profile: PicsProfile) -> None:
        assert isinstance(profile, PicsProfile)

    # -- section point types --

    def test_bo_point_type(self, profile: PicsProfile) -> None:
        assert all(isinstance(p, BoPoint) for p in profile.bo.points)

    def test_bi_point_type(self, profile: PicsProfile) -> None:
        assert all(isinstance(p, BiPoint) for p in profile.bi.points)

    def test_ao_point_type(self, profile: PicsProfile) -> None:
        assert all(isinstance(p, AoPoint) for p in profile.ao.points)

    def test_ai_point_type(self, profile: PicsProfile) -> None:
        assert all(isinstance(p, AiPoint) for p in profile.ai.points)

    def test_ctr_point_type(self, profile: PicsProfile) -> None:
        assert all(isinstance(p, CtrPoint) for p in profile.ctr)

    # -- base counts --

    def test_bo_base_count(self, profile: PicsProfile) -> None:
        assert len(profile.bo.points) == 1

    def test_bi_base_count(self, profile: PicsProfile) -> None:
        assert len(profile.bi.points) == 1

    def test_ao_base_count(self, profile: PicsProfile) -> None:
        assert len(profile.ao.points) == 2

    def test_ai_base_count(self, profile: PicsProfile) -> None:
        assert len(profile.ai.points) == 2

    def test_ctr_count(self, profile: PicsProfile) -> None:
        assert len(profile.ctr) == 2

    def test_curve_count(self, profile: PicsProfile) -> None:
        assert len(profile.ai.curves) == 1

    # -- field values --

    def test_bo_fields(self, profile: PicsProfile) -> None:
        bo = profile.bo.points[0]
        assert bo.point_index == 0
        assert bo.name == "System Set Lockout State"
        assert bo.assoc_bi == "BI11"
        assert bo.mandatory_1815 is True
        assert bo.mandatory_1547 is False

    def test_bi_event_class(self, profile: PicsProfile) -> None:
        assert profile.bi.points[0].event_class is EventClass.CLASS1

    def test_ai_event_class(self, profile: PicsProfile) -> None:
        assert profile.ai.points[0].event_class is EventClass.CLASS1
        assert profile.ai.points[1].event_class is EventClass.CLASS2

    def test_ai_engineering_value_preserved(self, profile: PicsProfile) -> None:
        # The loader keeps the engineering value; scaling happens at build time.
        assert profile.ai.points[0].value == pytest.approx(125.0)
        assert profile.ai.points[1].value == pytest.approx(-0.95)

    def test_ai_multiplier_offset(self, profile: PicsProfile) -> None:
        ai0 = profile.ai.points[0]
        assert ai0.multiplier == pytest.approx(0.1)
        assert ai0.offset == pytest.approx(5.0)
        assert ai0.minimum == 0
        assert ai0.maximum == 10000

    def test_ctr_frozen_fields(self, profile: PicsProfile) -> None:
        ctr0 = profile.ctr[0]
        assert ctr0.frozen_counter_exists is True
        assert ctr0.frozen_counter_event_class is EventClass.CLASS3
        assert ctr0.counter_event_class is EventClass.NONE
        ctr1 = profile.ctr[1]
        assert ctr1.frozen_counter_exists is False
        assert ctr1.counter_event_class is EventClass.CLASS1

    # -- UID verbatim (no normalization) --

    def test_uid_verbatim_with_underscores(self, profile: PicsProfile) -> None:
        # The underscores inside the dotted segment survive unchanged.
        assert profile.bo.points[0].iec_61850_uid == "DSTO.DEROpSt.disconnected_and_blocked"

    # -- equipment flattening --

    def test_bi_all_points_includes_equipment(self, profile: PicsProfile) -> None:
        # base BI0 + meter BI5000 + der BI6000
        indices = {p.point_index for p in profile.bi.all_points()}
        assert indices == {0, 5000, 6000}

    def test_ao_all_points_includes_equipment(self, profile: PicsProfile) -> None:
        # base AO0, AO249 + battery AO20000
        indices = {p.point_index for p in profile.ao.all_points()}
        assert indices == {0, 249, 20000}

    def test_ai_base_points_excludes_curves(self, profile: PicsProfile) -> None:
        # base AI0, AI1 + meter AI5100; curve points NOT here
        indices = {p.point_index for p in profile.ai.base_points()}
        assert indices == {0, 1, 5100}

    def test_ai_all_points_full_includes_curves(self, profile: PicsProfile) -> None:
        # base + equipment + all curve header/x/y points
        indices = {p.point_index for p in profile.ai.all_points_full()}
        expected = {0, 1, 5100, 329, 330, 331, 332, 333, 334, 433, 434}
        assert indices == expected

    def test_no_profile_point_dropped(self, profile: PicsProfile) -> None:
        # Every point across every section maps to a model point: assert the
        # total flattened count equals the sum of the raw JSON point counts.
        total = (
            len(profile.bo.all_points())
            + len(profile.bi.all_points())
            + len(profile.ao.all_points())
            + len(profile.ai.all_points_full())
            + len(profile.ctr)
        )
        # BO 1, BI 3, AO 3, AI 11 (2 base + 1 meter + 8 curve), CTR 2 = 20
        assert total == 20

    # -- curve structure --

    def test_curve_selector_association(self, profile: PicsProfile) -> None:
        curve = profile.ai.curves[0]
        # curve_type header carries the selector association back to the AO.
        assert curve.header[0].assoc_ao == "AO245"
        assert curve.header[0].point_index == 329

    def test_curve_parallel_arrays(self, profile: PicsProfile) -> None:
        curve = profile.ai.curves[0]
        assert [p.point_index for p in curve.x_values] == [333, 334]
        assert [p.point_index for p in curve.y_values] == [433, 434]

    # -- KeySheet --

    def test_keysheet_max_points(self, profile: PicsProfile) -> None:
        assert profile.key.max_points == 30000


# ===========================================================================
# load_profile error handling (loud failures, no silent defaults)
# ===========================================================================


class TestLoaderErrors:
    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_profile(Path("/nonexistent/profile-abc123.json"))

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_profile(bad)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        # A BO point missing 'name' must raise loudly, not default it.
        doc = _minimal_doc()
        doc["BO"]["points"] = [
            {
                "point_index": 0,
                "state_0": "a",
                "state_1": "b",
                "iec_61850_uid": "X.Y",
                "purpose": "p",
                "mandatory_1815": True,
                "mandatory_1547": False,
            }
        ]
        path = tmp_path / "missing.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(KeyError, match="name"):
            load_profile(path)

    def test_unknown_event_class_raises(self, tmp_path: Path) -> None:
        doc = _minimal_doc()
        doc["BI"]["points"] = [
            {
                "point_index": 0,
                "name": "x",
                "event_class": "Class9",
                "state_0": "a",
                "state_1": "b",
                "iec_61850_uid": "X.Y",
                "assoc_bo": None,
                "purpose": "p",
                "mandatory_1815": True,
                "mandatory_1547": False,
            }
        ]
        path = tmp_path / "badclass.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError, match="Unknown event_class"):
            load_profile(path)

    def test_zero_multiplier_raises(self, tmp_path: Path) -> None:
        doc = _minimal_doc()
        doc["AO"]["points"] = [
            {
                "point_index": 0,
                "name": "x",
                "minimum": 0,
                "maximum": 100,
                "multiplier": 0.0,
                "offset": 0.0,
                "units": "u",
                "iec_61850_uid": "X.Y",
                "assoc_ai": None,
                "purpose": "p",
                "mandatory_1815": True,
                "mandatory_1547": False,
            }
        ]
        path = tmp_path / "zeromult.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(ValueError, match="multiplier cannot be zero"):
            load_profile(path)


def _minimal_doc() -> dict:
    """A minimal valid PicsProfile document skeleton for negative tests."""
    return {
        "Key": {"max_points": 100},
        "BO": {"points": []},
        "BI": {"points": [], "meters": [], "ders": [], "inverters": [], "batteries": []},
        "AO": {"points": [], "meters": [], "inverters": [], "batteries": []},
        "AI": {
            "points": [],
            "meters": [],
            "ders": [],
            "inverters": [],
            "batteries": [],
            "curves": [],
            "schedules_bc": [],
            "schedules": [],
        },
        "CTR": [],
    }


# ===========================================================================
# Golden parse: the bundled full.json census
# ===========================================================================


class TestGoldenFullProfile:
    """Parse the real bundled full.json and assert its census. A mesa-tool
    schema change (renamed field, reordered struct) breaks this loudly."""

    @pytest.fixture()
    def full(self) -> PicsProfile:
        return load_profile(FULL_PROFILE)

    def test_bo_census(self, full: PicsProfile) -> None:
        assert len(full.bo.points) == 66

    def test_ctr_census(self, full: PicsProfile) -> None:
        assert len(full.ctr) == 8

    def test_curve_census(self, full: PicsProfile) -> None:
        assert len(full.ai.curves) == 4

    def test_schedule_census(self, full: PicsProfile) -> None:
        assert len(full.ai.schedules_bc) == 4
        assert len(full.ai.schedules) == 4

    def test_bi_base_census(self, full: PicsProfile) -> None:
        assert len(full.bi.points) == 134

    def test_ao_base_census(self, full: PicsProfile) -> None:
        assert len(full.ao.points) == 1153

    def test_ai_base_census(self, full: PicsProfile) -> None:
        assert len(full.ai.points) == 505

    def test_bi_equipment_instances(self, full: PicsProfile) -> None:
        # meters 1, ders 1, inverters 2, batteries 2 -> 6 instances
        assert len(full.bi.equipment) == 6

    def test_ao_equipment_instances(self, full: PicsProfile) -> None:
        # meters 1, inverters 2, batteries 2 -> 5 instances (no ders in AO)
        assert len(full.ao.equipment) == 5

    def test_curve_points_registered_at_absolute_indices(self, full: PicsProfile) -> None:
        # The base-only-registration trap: every curve AI point must be present
        # in all_points_full at its absolute index, not dropped.
        base_indices = {p.point_index for p in full.ai.base_points()}
        full_indices = {p.point_index for p in full.ai.all_points_full()}
        curve_only = full_indices - base_indices
        # curves + schedules add real AI points beyond the base set.
        assert len(curve_only) > 0
        # The first curve's curve_type header point (AI329) is one of them.
        assert 329 in full_indices
        assert 329 not in base_indices

    def test_uid_verbatim_on_full(self, full: PicsProfile) -> None:
        # A known verbatim UID with an interior dotted segment survives.
        ctr_uids = {c.iec_61850_uid for c in full.ctr}
        assert "MMTR.SupWh" in ctr_uids
