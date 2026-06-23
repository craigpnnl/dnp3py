"""Integration tests for MESA outstation with real profile.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.entities import EntityType, build_entities
from dnp3.mesa.outstation import MesaOutstation, create_mesa_outstation
from dnp3.mesa.profile import Profile, load_profile

PROFILE_PATH = Path(__file__).parent.parent.parent / "data" / "template" / "profile.json"


@pytest.fixture(scope="module")
def profile() -> Profile:
    """Load the real profile once for the module."""
    return load_profile(PROFILE_PATH)


@pytest.fixture(scope="module")
def mesa_outstation() -> MesaOutstation:
    """Create a full MESA outstation from the real profile."""
    return create_mesa_outstation(PROFILE_PATH)


# ---- Test 1: Profile loads successfully ------------------------------------


class TestProfileLoading:
    def test_profile_loads_successfully(self, profile: Profile) -> None:
        """load_profile returns a Profile without errors."""
        assert isinstance(profile, Profile)
        assert len(profile.binary_inputs.points) > 0
        assert len(profile.analog_inputs.points) > 0

    def test_profile_entity_counts(self, profile: Profile) -> None:
        """Entities dict has meters=2, ders=2, inverters=2, batteries=2."""
        assert profile.entities["meters"] == 2
        assert profile.entities["ders"] == 2
        assert profile.entities["inverters"] == 2
        assert profile.entities["batteries"] == 2


# ---- Test 3: Database point counts ----------------------------------------


class TestDatabasePointCounts:
    def test_database_point_counts(self, profile: Profile) -> None:
        """Database built from real profile has expected point counts."""
        database, ao_store = build_database(profile)

        bi_count = database.binary_input_count
        bo_count = database.binary_output_count
        ai_count = database.analog_input_count
        ao_count = len(ao_store)

        # All counts must be > 0
        assert bi_count > 0, f"Expected BI > 0, got {bi_count}"
        assert bo_count > 0, f"Expected BO > 0, got {bo_count}"
        assert ai_count > 0, f"Expected AI > 0, got {ai_count}"
        assert ao_count > 0, f"Expected AO store > 0, got {ao_count}"

        # Exact counts from the real profile (supported=True only)
        assert bi_count == 342, f"Expected 342 BI, got {bi_count}"
        assert bo_count == 276, f"Expected 276 BO, got {bo_count}"
        assert ai_count == 1952, f"Expected 1952 AI, got {ai_count}"
        assert ao_count == 1176, f"Expected 1176 AO, got {ao_count}"


# ---- Test 4: Full outstation factory works ---------------------------------


class TestOutstationFactory:
    def test_create_mesa_outstation(self, mesa_outstation: MesaOutstation) -> None:
        """create_mesa_outstation returns a MesaOutstation without errors."""
        assert isinstance(mesa_outstation, MesaOutstation)
        assert mesa_outstation.profile is not None
        assert mesa_outstation.database is not None
        assert mesa_outstation.ao_store is not None
        assert mesa_outstation.handler is not None
        assert mesa_outstation.outstation is not None


# ---- Test 5: Entity building with defaults ---------------------------------


class TestEntityBuilding:
    def test_build_entities_defaults(self, profile: Profile) -> None:
        """build_entities returns entities for all 4 types, 2 each = 8."""
        entities = build_entities(profile)
        assert len(entities) == 8

        by_type = {}
        for e in entities:
            by_type.setdefault(e.entity_type, []).append(e)

        assert len(by_type[EntityType.METER]) == 2
        assert len(by_type[EntityType.DER]) == 2
        assert len(by_type[EntityType.INVERTER]) == 2
        assert len(by_type[EntityType.BATTERY]) == 2

    def test_build_entities_with_overrides(self, profile: Profile) -> None:
        """build_entities with overrides correctly filters entity counts."""
        entities = build_entities(profile, {"meters": 1, "batteries": 1})

        by_type = {}
        for e in entities:
            by_type.setdefault(e.entity_type, []).append(e)

        assert len(by_type.get(EntityType.METER, [])) == 1
        assert len(by_type.get(EntityType.BATTERY, [])) == 1
        # DER and Inverter still get defaults from profile (2 each)
        assert len(by_type.get(EntityType.DER, [])) == 2
        assert len(by_type.get(EntityType.INVERTER, [])) == 2


# ---- Test 7: Entity points at expected offsets -----------------------------


class TestEntityPointOffsets:
    def test_meter_entity_bi_indices(self, profile: Profile) -> None:
        """Meter entities have BI indices >= 5000 and < 10000."""
        entities = build_entities(profile)
        meters = [e for e in entities if e.entity_type == EntityType.METER]
        assert len(meters) > 0

        from dnp3.mesa.profile import PointType

        for meter in meters:
            bi_indices = meter.point_indices.get(PointType.BINARY_INPUT, [])
            for idx in bi_indices:
                assert 5000 <= idx < 10000, f"Meter BI index {idx} outside [5000, 10000)"

    def test_battery_entity_bi_indices(self, profile: Profile) -> None:
        """Battery entities have BI indices >= 20000 and < 30000."""
        entities = build_entities(profile)
        batteries = [e for e in entities if e.entity_type == EntityType.BATTERY]
        assert len(batteries) > 0

        from dnp3.mesa.profile import PointType

        for battery in batteries:
            bi_indices = battery.point_indices.get(PointType.BINARY_INPUT, [])
            for idx in bi_indices:
                assert 20000 <= idx < 30000, f"Battery BI index {idx} outside [20000, 30000)"


# ---- Test 8: AO-AI associated index mirroring -----------------------------


class TestAOAIMirroring:
    def test_ao_ai_associated_index_mirroring(self) -> None:
        """Direct operate AO0 -> mirrors value to AI29."""
        mesa = create_mesa_outstation(PROFILE_PATH)

        # AO0 has associated_index=AI29 in the real profile
        result = mesa.handler.direct_operate_analog_output(index=0, value=50.0)
        assert result.status == CommandStatus.SUCCESS

        # Verify AI29 was updated
        ai_point = mesa.database.get_analog_input(29)
        assert ai_point is not None, "AI29 not found in database"
        assert ai_point.value == 50.0, f"Expected AI29 value 50.0, got {ai_point.value}"

        # Verify AO store was updated
        ao_val = mesa.ao_store.get(0)
        assert ao_val is not None
        assert ao_val.value == 50.0


# ---- Test 9: CLI dry run with reduced entities -----------------------------


class TestReducedEntities:
    def test_create_with_entity_overrides(self) -> None:
        """Outstation with reduced entity overrides works and has fewer entities."""
        overrides = {"meters": 1, "batteries": 1, "ders": 0, "inverters": 0}
        mesa = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)

        assert isinstance(mesa, MesaOutstation)

        by_type = {}
        for e in mesa.entities:
            by_type.setdefault(e.entity_type, []).append(e)

        assert len(by_type.get(EntityType.METER, [])) == 1
        assert len(by_type.get(EntityType.BATTERY, [])) == 1
        assert len(by_type.get(EntityType.DER, [])) == 0
        assert len(by_type.get(EntityType.INVERTER, [])) == 0
        assert len(mesa.entities) == 2

    def test_reduced_entities_reduces_database_points(self) -> None:
        """With entity overrides, database should have fewer points than full profile."""
        full_mesa = create_mesa_outstation(PROFILE_PATH)
        overrides = {"meters": 1, "batteries": 1, "ders": 0, "inverters": 0}
        reduced_mesa = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)

        # Reduced outstation must have strictly fewer points
        assert reduced_mesa.database.binary_input_count < full_mesa.database.binary_input_count
        assert reduced_mesa.database.analog_input_count < full_mesa.database.analog_input_count
        assert len(reduced_mesa.ao_store) < len(full_mesa.ao_store)

    def test_full_exclusion_keeps_only_scada_points(self) -> None:
        """With all entities at 0, only SCADA (non-entity) points remain."""
        overrides = {"meters": 0, "batteries": 0, "ders": 0, "inverters": 0}
        mesa = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)

        # Should still have some points (SCADA-level points have no entity_type)
        assert mesa.database.binary_input_count > 0
        assert mesa.database.analog_input_count > 0


# ---- Test 10: BO command handling ------------------------------------------


class TestBOCommandHandling:
    def test_direct_operate_bo_latch_on(self) -> None:
        """Direct operate BO0 with LATCH_ON succeeds and updates database."""
        mesa = create_mesa_outstation(PROFILE_PATH)

        result = mesa.handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.SUCCESS

        bo_point = mesa.database.get_binary_output(0)
        assert bo_point is not None, "BO0 not found in database"
        assert bo_point.value is True, f"Expected BO0=True, got {bo_point.value}"

    def test_direct_operate_bo_latch_off(self) -> None:
        """Direct operate BO0 with LATCH_OFF succeeds and updates database."""
        mesa = create_mesa_outstation(PROFILE_PATH)

        # First set ON
        mesa.handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        # Then set OFF
        result = mesa.handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_OFF,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.SUCCESS

        bo_point = mesa.database.get_binary_output(0)
        assert bo_point is not None
        assert bo_point.value is False, f"Expected BO0=False, got {bo_point.value}"
