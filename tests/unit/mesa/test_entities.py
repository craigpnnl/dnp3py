"""Tests for the MESA entity model under the PICS profile format.

Equipment instances are explicit structs in the profile; an entity is one
instance's points unioned across sections. The count-override slices instances.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.mesa.entities import Entity, EntityType, build_entities, compute_excluded_indices
from dnp3.mesa.profile import PicsProfile, PointType, load_profile

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PROFILE = FIXTURE_DIR / "test_profile.json"


class TestEntityType:
    def test_four_members(self) -> None:
        assert len(EntityType) == 4

    def test_from_profile_string(self) -> None:
        assert EntityType.from_profile_string("Meter") is EntityType.METER
        assert EntityType.from_profile_string("DER_Unit") is EntityType.DER
        assert EntityType.from_profile_string("Inverter") is EntityType.INVERTER
        assert EntityType.from_profile_string("Battery") is EntityType.BATTERY

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            EntityType.from_profile_string("Nope")


class TestEntity:
    def test_construction(self) -> None:
        entity = Entity(
            entity_type=EntityType.METER,
            entity_number=1,
            point_indices={PointType.ANALOG_INPUT: [5100]},
        )
        assert entity.entity_type is EntityType.METER
        assert entity.entity_number == 1
        assert entity.point_indices[PointType.ANALOG_INPUT] == [5100]


class TestBuildEntities:
    @pytest.fixture()
    def profile(self) -> PicsProfile:
        return load_profile(FIXTURE_PROFILE)

    def test_returns_entities(self, profile: PicsProfile) -> None:
        result = build_entities(profile)
        assert all(isinstance(e, Entity) for e in result)

    def test_default_returns_meter_der_battery(self, profile: PicsProfile) -> None:
        # Fixture: 1 meter (BI+AI), 1 der (BI), 1 battery (AO) -> 3 entities.
        result = build_entities(profile)
        types = {e.entity_type for e in result}
        assert types == {EntityType.METER, EntityType.DER, EntityType.BATTERY}

    def test_meter_has_bi_and_ai(self, profile: PicsProfile) -> None:
        result = build_entities(profile)
        meter = next(e for e in result if e.entity_type is EntityType.METER)
        assert 5000 in meter.point_indices[PointType.BINARY_INPUT]
        assert 5100 in meter.point_indices[PointType.ANALOG_INPUT]

    def test_battery_has_ao(self, profile: PicsProfile) -> None:
        result = build_entities(profile)
        battery = next(e for e in result if e.entity_type is EntityType.BATTERY)
        assert 20000 in battery.point_indices[PointType.ANALOG_OUTPUT]

    def test_override_meters_zero_excludes_meter(self, profile: PicsProfile) -> None:
        result = build_entities(profile, overrides={"meters": 0})
        types = {e.entity_type for e in result}
        assert EntityType.METER not in types
        assert EntityType.BATTERY in types

    def test_override_all_zero_returns_empty(self, profile: PicsProfile) -> None:
        result = build_entities(profile, overrides={"meters": 0, "ders": 0, "inverters": 0, "batteries": 0})
        assert result == []

    def test_scada_points_not_in_any_entity(self, profile: PicsProfile) -> None:
        result = build_entities(profile)
        seen: dict[PointType, set[int]] = {}
        for entity in result:
            for pt, indices in entity.point_indices.items():
                seen.setdefault(pt, set()).update(indices)
        for pt, indices in seen.items():
            assert 0 not in indices, f"SCADA index 0 leaked into {pt.name}"

    def test_result_sorted(self, profile: PicsProfile) -> None:
        result = build_entities(profile)
        keys = [(e.entity_type.value, e.entity_number) for e in result]
        assert keys == sorted(keys)


class TestComputeExcludedIndices:
    @pytest.fixture()
    def profile(self) -> PicsProfile:
        return load_profile(FIXTURE_PROFILE)

    def test_no_overrides_returns_empty(self, profile: PicsProfile) -> None:
        assert compute_excluded_indices(profile) == {}

    def test_meters_zero_excludes_meter_bi(self, profile: PicsProfile) -> None:
        result = compute_excluded_indices(profile, overrides={"meters": 0})
        assert 5000 in result[PointType.BINARY_INPUT]

    def test_meters_zero_excludes_meter_ai(self, profile: PicsProfile) -> None:
        result = compute_excluded_indices(profile, overrides={"meters": 0})
        assert 5100 in result[PointType.ANALOG_INPUT]

    def test_batteries_zero_excludes_battery_ao(self, profile: PicsProfile) -> None:
        result = compute_excluded_indices(profile, overrides={"batteries": 0})
        assert 20000 in result[PointType.ANALOG_OUTPUT]

    def test_meters_zero_does_not_exclude_scada(self, profile: PicsProfile) -> None:
        result = compute_excluded_indices(profile, overrides={"meters": 0})
        assert 0 not in result.get(PointType.BINARY_INPUT, set())
        assert 0 not in result.get(PointType.ANALOG_INPUT, set())

    def test_battery_not_excluded_when_only_meters_zeroed(self, profile: PicsProfile) -> None:
        result = compute_excluded_indices(profile, overrides={"meters": 0})
        assert 20000 not in result.get(PointType.ANALOG_OUTPUT, set())
