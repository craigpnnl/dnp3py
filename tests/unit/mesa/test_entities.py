"""RED phase: Failing tests for MESA entity model.

These tests define the expected API for EntityType, Entity, and build_entities.
The implementation module (dnp3.mesa.entities) does not exist yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PROFILE = FIXTURE_DIR / "test_profile.json"


# ---------------------------------------------------------------------------
# EntityType enum tests
# ---------------------------------------------------------------------------


class TestEntityType:
    """Tests for the EntityType enum."""

    def test_meter_value_exists(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.METER is not None

    def test_der_value_exists(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.DER is not None

    def test_inverter_value_exists(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.INVERTER is not None

    def test_battery_value_exists(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.BATTERY is not None

    def test_has_exactly_four_members(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert len(EntityType) == 4

    def test_from_profile_string_meter(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.from_profile_string("Meter") is EntityType.METER

    def test_from_profile_string_der_unit(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.from_profile_string("DER_Unit") is EntityType.DER

    def test_from_profile_string_battery(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.from_profile_string("Battery") is EntityType.BATTERY

    def test_from_profile_string_inverter(self) -> None:
        from dnp3.mesa.entities import EntityType

        assert EntityType.from_profile_string("Inverter") is EntityType.INVERTER

    def test_from_profile_string_unknown_raises(self) -> None:
        from dnp3.mesa.entities import EntityType

        with pytest.raises(ValueError, match="Unknown"):
            EntityType.from_profile_string("Unknown")


# ---------------------------------------------------------------------------
# Entity dataclass tests
# ---------------------------------------------------------------------------


class TestEntity:
    """Tests for the Entity dataclass."""

    def test_construction(self) -> None:
        from dnp3.mesa.entities import Entity, EntityType
        from dnp3.mesa.profile import PointType

        entity = Entity(
            entity_type=EntityType.METER,
            entity_number=1,
            point_indices={PointType.ANALOG_INPUT: [5000, 5001]},
        )

        assert entity.entity_type is EntityType.METER
        assert entity.entity_number == 1
        assert PointType.ANALOG_INPUT in entity.point_indices

    def test_access_point_indices_by_point_type(self) -> None:
        from dnp3.mesa.entities import Entity, EntityType
        from dnp3.mesa.profile import PointType

        indices = {
            PointType.BINARY_INPUT: [5000],
            PointType.ANALOG_INPUT: [5000, 5001],
            PointType.ANALOG_OUTPUT: [20000],
        }
        entity = Entity(
            entity_type=EntityType.BATTERY,
            entity_number=1,
            point_indices=indices,
        )

        assert entity.point_indices[PointType.BINARY_INPUT] == [5000]
        assert entity.point_indices[PointType.ANALOG_INPUT] == [5000, 5001]
        assert entity.point_indices[PointType.ANALOG_OUTPUT] == [20000]

    def test_empty_point_indices(self) -> None:
        from dnp3.mesa.entities import Entity, EntityType

        entity = Entity(
            entity_type=EntityType.INVERTER,
            entity_number=1,
            point_indices={},
        )

        assert entity.point_indices == {}


# ---------------------------------------------------------------------------
# build_entities tests (using test fixture profile)
# ---------------------------------------------------------------------------


class TestBuildEntities:
    """Tests for the build_entities function using the test fixture profile."""

    @pytest.fixture()
    def profile(self):
        """Load the test fixture profile."""
        from dnp3.mesa.profile import load_profile

        return load_profile(FIXTURE_PROFILE)

    def test_returns_list_of_entities(self, profile) -> None:
        from dnp3.mesa.entities import Entity, build_entities

        result = build_entities(profile)

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, Entity)

    def test_default_entities_returns_two(self, profile) -> None:
        """Fixture has meters=1 and batteries=1, so expect 2 entities."""
        from dnp3.mesa.entities import build_entities

        result = build_entities(profile)

        assert len(result) == 2

    def test_meter_entity_type_and_number(self, profile) -> None:
        from dnp3.mesa.entities import EntityType, build_entities

        result = build_entities(profile)
        meter = next(e for e in result if e.entity_type is EntityType.METER)

        assert meter.entity_number == 1
        assert meter.entity_type is EntityType.METER

    def test_meter_has_binary_input_5000(self, profile) -> None:
        """BI5000 is a Meter entity_number=1 point in the fixture."""
        from dnp3.mesa.entities import EntityType, build_entities
        from dnp3.mesa.profile import PointType

        result = build_entities(profile)
        meter = next(e for e in result if e.entity_type is EntityType.METER)

        assert 5000 in meter.point_indices[PointType.BINARY_INPUT]

    def test_meter_has_analog_input_5000(self, profile) -> None:
        """AI5000 is a Meter entity_number=1 point in the fixture."""
        from dnp3.mesa.entities import EntityType, build_entities
        from dnp3.mesa.profile import PointType

        result = build_entities(profile)
        meter = next(e for e in result if e.entity_type is EntityType.METER)

        assert 5000 in meter.point_indices[PointType.ANALOG_INPUT]

    def test_battery_entity_type_and_number(self, profile) -> None:
        from dnp3.mesa.entities import EntityType, build_entities

        result = build_entities(profile)
        battery = next(e for e in result if e.entity_type is EntityType.BATTERY)

        assert battery.entity_number == 1
        assert battery.entity_type is EntityType.BATTERY

    def test_battery_has_analog_output_20000(self, profile) -> None:
        """AO20000 is a Battery entity_number=1 point in the fixture."""
        from dnp3.mesa.entities import EntityType, build_entities
        from dnp3.mesa.profile import PointType

        result = build_entities(profile)
        battery = next(e for e in result if e.entity_type is EntityType.BATTERY)

        assert 20000 in battery.point_indices[PointType.ANALOG_OUTPUT]

    def test_override_meters_zero_excludes_meter(self, profile) -> None:
        from dnp3.mesa.entities import EntityType, build_entities

        result = build_entities(profile, overrides={"meters": 0})

        entity_types = [e.entity_type for e in result]
        assert EntityType.METER not in entity_types
        assert EntityType.BATTERY in entity_types

    def test_override_batteries_zero_excludes_battery(self, profile) -> None:
        from dnp3.mesa.entities import EntityType, build_entities

        result = build_entities(profile, overrides={"batteries": 0})

        entity_types = [e.entity_type for e in result]
        assert EntityType.BATTERY not in entity_types
        assert EntityType.METER in entity_types

    def test_override_all_zero_returns_empty(self, profile) -> None:
        from dnp3.mesa.entities import build_entities

        result = build_entities(profile, overrides={"meters": 0, "batteries": 0})

        assert result == []

    def test_scada_points_not_in_any_entity(self, profile) -> None:
        """Non-entity SCADA points (BO0, BI0, AO0, AI0) must not appear in entities."""
        from dnp3.mesa.entities import build_entities
        from dnp3.mesa.profile import PointType

        result = build_entities(profile)

        all_indices: dict[PointType, set[int]] = {}
        for entity in result:
            for pt, indices in entity.point_indices.items():
                all_indices.setdefault(pt, set()).update(indices)

        # Index 0 points are SCADA-level, not entity-level
        for pt in PointType:
            if pt in all_indices:
                assert 0 not in all_indices[pt], f"SCADA point index 0 for {pt.name} should not appear in any entity"

    def test_result_sorted_by_entity_type_then_number(self, profile) -> None:
        from dnp3.mesa.entities import build_entities

        result = build_entities(profile)

        keys = [(e.entity_type.value, e.entity_number) for e in result]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# compute_excluded_indices tests
# ---------------------------------------------------------------------------


class TestComputeExcludedIndices:
    """Tests for the compute_excluded_indices function."""

    @pytest.fixture()
    def profile(self):
        from dnp3.mesa.profile import load_profile

        return load_profile(FIXTURE_PROFILE)

    def test_no_overrides_returns_empty(self, profile) -> None:
        """When overrides is None, nothing is excluded."""
        from dnp3.mesa.entities import compute_excluded_indices

        result = compute_excluded_indices(profile)

        assert result == {}

    def test_meters_zero_excludes_meter_bi(self, profile) -> None:
        """Overriding meters=0 should exclude BI5000 (Meter entity_number=1)."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"meters": 0})

        assert PointType.BINARY_INPUT in result
        assert 5000 in result[PointType.BINARY_INPUT]

    def test_meters_zero_excludes_meter_ai(self, profile) -> None:
        """Overriding meters=0 should exclude AI5000 (Meter entity_number=1)."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"meters": 0})

        assert PointType.ANALOG_INPUT in result
        assert 5000 in result[PointType.ANALOG_INPUT]

    def test_batteries_zero_excludes_battery_ao(self, profile) -> None:
        """Overriding batteries=0 should exclude AO20000 (Battery entity_number=1)."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"batteries": 0})

        assert PointType.ANALOG_OUTPUT in result
        assert 20000 in result[PointType.ANALOG_OUTPUT]

    def test_meters_zero_does_not_exclude_scada_points(self, profile) -> None:
        """SCADA points (BI0, AI0, etc.) have no entity_type and must not be excluded."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"meters": 0})

        # Index 0 points are non-entity SCADA points
        assert 0 not in result.get(PointType.BINARY_INPUT, set())
        assert 0 not in result.get(PointType.ANALOG_INPUT, set())

    def test_all_zero_excludes_all_entity_points(self, profile) -> None:
        """Overriding all entity types to 0 should exclude all entity points."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"meters": 0, "batteries": 0})

        assert 5000 in result.get(PointType.BINARY_INPUT, set())
        assert 5000 in result.get(PointType.ANALOG_INPUT, set())
        assert 20000 in result.get(PointType.ANALOG_OUTPUT, set())

    def test_default_counts_preserved_for_unspecified_keys(self, profile) -> None:
        """Overriding only meters=0 should still allow battery points (profile default)."""
        from dnp3.mesa.entities import compute_excluded_indices
        from dnp3.mesa.profile import PointType

        result = compute_excluded_indices(profile, overrides={"meters": 0})

        # Battery AO20000 should NOT be excluded (profile.entities has batteries=1)
        assert 20000 not in result.get(PointType.ANALOG_OUTPUT, set())
