"""Integration tests for the MESA outstation against the bundled full.json.

These exercise the loader, database builder, entity model, and command handler
end to end on the real PICS profile. Point counts are asserted exactly so a
mesa-tool schema or point-map change breaks loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.entities import EntityType, build_entities
from dnp3.mesa.outstation import MesaOutstation, create_mesa_outstation
from dnp3.mesa.profile import PicsProfile, PointType, load_profile

PROFILE_PATH = Path(__file__).parents[2] / "data" / "profiles" / "full.json"


@pytest.fixture(scope="module")
def profile() -> PicsProfile:
    return load_profile(PROFILE_PATH)


@pytest.fixture(scope="module")
def mesa_outstation() -> MesaOutstation:
    return create_mesa_outstation(PROFILE_PATH)


class TestProfileLoading:
    def test_profile_loads(self, profile: PicsProfile) -> None:
        assert isinstance(profile, PicsProfile)
        assert len(profile.bi.points) > 0
        assert len(profile.ai.points) > 0

    def test_full_census(self, profile: PicsProfile) -> None:
        assert len(profile.bo.points) == 66
        assert len(profile.bi.points) == 134
        assert len(profile.ao.points) == 1153
        assert len(profile.ai.points) == 505
        assert len(profile.ctr) == 8
        assert len(profile.ai.curves) == 4


class TestDatabasePointCounts:
    def test_build_database_counts(self, profile: PicsProfile) -> None:
        database, ao_store = build_database(profile)
        # Deduplicated by DNP3 index: the four curves overlay one index range.
        assert database.binary_input_count == 329
        assert database.binary_output_count == 66
        assert database.analog_input_count == 1527
        assert len(ao_store) == 1197


class TestOutstationFactory:
    def test_create(self, mesa_outstation: MesaOutstation) -> None:
        assert isinstance(mesa_outstation, MesaOutstation)
        assert mesa_outstation.database is not None
        assert mesa_outstation.ao_store is not None
        assert mesa_outstation.handler is not None
        assert mesa_outstation.outstation is not None


class TestEntityBuilding:
    def test_default_entity_instances(self, profile: PicsProfile) -> None:
        entities = build_entities(profile)
        by_type: dict[EntityType, int] = {}
        for e in entities:
            by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        # BI equipment: meters 1, ders 1, inverters 2, batteries 2. AO/AI add
        # more instances of the same numbers, unioned per (type, instance).
        assert by_type[EntityType.METER] == 1
        assert by_type[EntityType.DER] == 1
        assert by_type[EntityType.INVERTER] == 2
        assert by_type[EntityType.BATTERY] == 2

    def test_override_reduces_instances(self, profile: PicsProfile) -> None:
        entities = build_entities(profile, {"inverters": 1, "batteries": 1})
        by_type: dict[EntityType, int] = {}
        for e in entities:
            by_type[e.entity_type] = by_type.get(e.entity_type, 0) + 1
        assert by_type[EntityType.INVERTER] == 1
        assert by_type[EntityType.BATTERY] == 1
        assert by_type[EntityType.METER] == 1


class TestScaledAnalogInput:
    def test_ai_stored_as_transmission_integer(self, mesa_outstation: MesaOutstation) -> None:
        # AI0: value 1.1, multiplier 0.01, offset 0 -> raw = 110.
        point = mesa_outstation.database.get_analog_input(0)
        assert point is not None
        assert point.value == 110


class TestAOAIMirroring:
    def test_ao0_mirrors_to_ai29(self) -> None:
        mesa = create_mesa_outstation(PROFILE_PATH)
        # AO0 has assoc_ai "AI29" in full.json.
        result = mesa.handler.direct_operate_analog_output(index=0, value=50)
        assert result.status == CommandStatus.SUCCESS
        ai_point = mesa.database.get_analog_input(29)
        assert ai_point is not None
        assert ai_point.value == 50
        ao_val = mesa.ao_store.get(0)
        assert ao_val is not None
        assert ao_val.value == 50


class TestReducedEntities:
    def test_reduced_entities_reduce_points(self) -> None:
        full_mesa = create_mesa_outstation(PROFILE_PATH)
        overrides = {"meters": 0, "ders": 0, "inverters": 0, "batteries": 0}
        reduced = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)
        assert reduced.database.binary_input_count < full_mesa.database.binary_input_count
        assert reduced.database.analog_input_count < full_mesa.database.analog_input_count

    def test_full_exclusion_keeps_base_points(self) -> None:
        overrides = {"meters": 0, "ders": 0, "inverters": 0, "batteries": 0}
        mesa = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)
        assert mesa.database.binary_input_count > 0
        assert mesa.database.analog_input_count > 0

    def test_scada_base_index_survives_full_exclusion(self) -> None:
        overrides = {"meters": 0, "ders": 0, "inverters": 0, "batteries": 0}
        mesa = create_mesa_outstation(PROFILE_PATH, entity_overrides=overrides)
        # A base (non-equipment) BI index remains.
        assert mesa.database.get_binary_input(0) is not None
        _ = PointType  # imported for parity with unit tests; base points remain.


class TestBOCommandHandling:
    def test_direct_operate_bo_latch_on(self) -> None:
        mesa = create_mesa_outstation(PROFILE_PATH)
        result = mesa.handler.direct_operate_binary_output(
            index=0, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0
        )
        assert result.status == CommandStatus.SUCCESS
        bo_point = mesa.database.get_binary_output(0)
        assert bo_point is not None
        assert bo_point.value is True

    def test_direct_operate_bo_latch_off(self) -> None:
        mesa = create_mesa_outstation(PROFILE_PATH)
        mesa.handler.direct_operate_binary_output(index=0, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0)
        result = mesa.handler.direct_operate_binary_output(
            index=0, code=ControlCode.LATCH_OFF, count=1, on_time=0, off_time=0
        )
        assert result.status == CommandStatus.SUCCESS
        bo_point = mesa.database.get_binary_output(0)
        assert bo_point is not None
        assert bo_point.value is False
