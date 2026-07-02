"""Tests for the MESA outstation factory under the PICS profile format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnp3.database import AnalogInputConfig, Database, DatabaseConfig
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.mesa.entities import EntityType
from dnp3.mesa.outstation import MesaOutstation, _build_associated_indices, create_mesa_outstation
from dnp3.mesa.profile import PicsProfile, PointType, load_profile
from dnp3.outstation import Outstation

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"


@pytest.fixture()
def mesa() -> MesaOutstation:
    return create_mesa_outstation(TEST_PROFILE)


class TestCreateMesaOutstation:
    def test_returns_mesa_outstation(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa, MesaOutstation)

    def test_database_type(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.database, Database)

    def test_outstation_type(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.outstation, Outstation)

    def test_handler_type(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.handler, MesaCommandHandler)

    def test_ao_store_type(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.ao_store, AnalogOutputStore)

    # -- Point counts (new fixture) --

    def test_binary_input_count(self, mesa: MesaOutstation) -> None:
        # base BI0 + meter BI5000 + der BI6000
        assert mesa.database.binary_input_count == 3

    def test_binary_output_count(self, mesa: MesaOutstation) -> None:
        assert mesa.database.binary_output_count == 1

    def test_analog_input_count(self, mesa: MesaOutstation) -> None:
        # base AI0, AI1 + meter AI5100 + 8 curve points
        assert mesa.database.analog_input_count == 11

    def test_ao_store_length(self, mesa: MesaOutstation) -> None:
        assert len(mesa.ao_store) == 3

    # -- Entities --

    def test_entity_count(self, mesa: MesaOutstation) -> None:
        # meter + der + battery
        assert len(mesa.entities) == 3

    def test_entity_types(self, mesa: MesaOutstation) -> None:
        types = {e.entity_type for e in mesa.entities}
        assert types == {EntityType.METER, EntityType.DER, EntityType.BATTERY}

    def test_override_removes_meters(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        types = {e.entity_type for e in mesa.entities}
        assert EntityType.METER not in types

    def test_override_meters_zero_removes_bi5000(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        assert mesa.database.get_binary_input(5000) is None

    def test_override_meters_zero_removes_ai5100(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        assert mesa.database.get_analog_input(5100) is None

    def test_override_batteries_zero_removes_ao20000(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"batteries": 0})
        assert mesa.ao_store.get(20000) is None

    # -- Association mirror (transmission passthrough) --

    def test_associated_ao0_mirrors_to_ai0(self, mesa: MesaOutstation) -> None:
        # AO0 has assoc_ai "AI0"; the mirror writes the value through to AI0.
        result = mesa.handler.direct_operate_analog_output(index=0, value=42.0)
        assert result.status.name == "SUCCESS"
        ai_point = mesa.database.get_analog_input(0)
        assert ai_point is not None
        assert ai_point.value == 42.0

    # -- Config --

    def test_default_host_port(self, mesa: MesaOutstation) -> None:
        assert mesa.host == "0.0.0.0"
        assert mesa.port == 20000

    def test_custom_host_port(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, host="127.0.0.1", port=30000)
        assert mesa.host == "127.0.0.1"
        assert mesa.port == 30000

    def test_custom_address(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, address=10, master_address=5)
        assert mesa.outstation.config.address == 10
        assert mesa.outstation.config.master_address == 5

    def test_profile_is_pics_profile(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.profile, PicsProfile)
        assert len(mesa.profile.ao.all_points()) == 3


class TestBuildAssociatedIndices:
    @pytest.fixture()
    def profile(self) -> PicsProfile:
        return load_profile(TEST_PROFILE)

    def _make_db_with_ai(self, *ai_indices: int) -> Database:
        db = Database(config=DatabaseConfig(max_analog_inputs=len(ai_indices) + 5))
        for idx in ai_indices:
            db.add_analog_input(idx, AnalogInputConfig())
        return db

    def test_ao0_maps_to_ai0(self, profile: PicsProfile) -> None:
        db = self._make_db_with_ai(0, 5100)
        result = _build_associated_indices(profile, db)
        assert 0 in result
        point_type_str, target_index = result[0]
        assert point_type_str == PointType.ANALOG_INPUT.value
        assert target_index == 0

    def test_ao_without_assoc_ai_absent(self, profile: PicsProfile) -> None:
        # AO20000 (battery) has assoc_ai null -> not in the result.
        db = self._make_db_with_ai(0, 5100)
        result = _build_associated_indices(profile, db)
        assert 20000 not in result

    def test_missing_base_ai_target_skipped(self, profile: PicsProfile) -> None:
        # AO0 -> AI0; when AI0 is absent from the DB, the plain-mirror
        # association is skipped (its target may live in a curve sub-group in
        # the real profile). It must not raise.
        db = self._make_db_with_ai(5100)
        result = _build_associated_indices(profile, db)
        assert 0 not in result

    def test_malformed_assoc_ai_raises(self, profile: PicsProfile, tmp_path: Path) -> None:
        bad_data = json.loads(TEST_PROFILE.read_text())
        bad_data["AO"]["points"][0]["assoc_ai"] = "XX999"
        bad_path = tmp_path / "bad.json"
        bad_path.write_text(json.dumps(bad_data), encoding="utf-8")
        bad_profile = load_profile(bad_path)
        db = self._make_db_with_ai(0)
        with pytest.raises(ValueError, match="malformed assoc_ai"):
            _build_associated_indices(bad_profile, db)

    def test_excluded_ao_skipped(self, profile: PicsProfile) -> None:
        db = self._make_db_with_ai(5100)
        excluded = {PointType.ANALOG_OUTPUT: {0}}
        result = _build_associated_indices(profile, db, excluded_indices=excluded)
        assert 0 not in result
