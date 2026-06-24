"""Tests for the MESA outstation factory module.

RED phase: These tests define the expected API for
dnp3.mesa.outstation.create_mesa_outstation before implementation exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnp3.database import AnalogInputConfig, Database, DatabaseConfig
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.mesa.entities import EntityType
from dnp3.mesa.outstation import MesaOutstation, _build_associated_indices, create_mesa_outstation
from dnp3.mesa.profile import PointType, load_profile
from dnp3.outstation import Outstation

# ---------------------------------------------------------------------------
# Fixture path helper
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_PROFILE = FIXTURE_DIR / "test_profile.json"


@pytest.fixture()
def mesa():
    """Create a MesaOutstation from the test profile."""
    return create_mesa_outstation(TEST_PROFILE)


# ---------------------------------------------------------------------------
# Factory function returns correct type
# ---------------------------------------------------------------------------


class TestCreateMesaOutstation:
    """Tests for create_mesa_outstation factory function."""

    def test_returns_mesa_outstation_instance(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa, MesaOutstation)

    def test_database_is_database_instance(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.database, Database)

    def test_outstation_is_outstation_instance(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.outstation, Outstation)

    def test_handler_is_mesa_command_handler(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.handler, MesaCommandHandler)

    def test_ao_store_is_analog_output_store(self, mesa: MesaOutstation) -> None:
        assert isinstance(mesa.ao_store, AnalogOutputStore)

    # -- Point counts -------------------------------------------------------

    def test_binary_input_count(self, mesa: MesaOutstation) -> None:
        """Test profile has BI0 and BI5000 = 2 binary inputs."""
        assert mesa.database.binary_input_count == 2

    def test_binary_output_count(self, mesa: MesaOutstation) -> None:
        """Test profile has BO0 (BO1 unsupported) = 1 binary output."""
        assert mesa.database.binary_output_count == 1

    def test_analog_input_count(self, mesa: MesaOutstation) -> None:
        """Test profile has AI0 and AI5000 = 2 analog inputs."""
        assert mesa.database.analog_input_count == 2

    def test_ao_store_length(self, mesa: MesaOutstation) -> None:
        """Test profile has AO0, AO20000, AO249 (unbounded curve point) = 3 analog outputs."""
        assert len(mesa.ao_store) == 3

    # -- Entities -----------------------------------------------------------

    def test_entity_count(self, mesa: MesaOutstation) -> None:
        """Test profile: 1 meter + 1 battery = 2 entities."""
        assert len(mesa.entities) == 2

    def test_entity_types(self, mesa: MesaOutstation) -> None:
        """Entities should include a battery and a meter."""
        types = {e.entity_type for e in mesa.entities}
        assert EntityType.METER in types
        assert EntityType.BATTERY in types

    # -- Entity overrides ---------------------------------------------------

    def test_entity_override_removes_meters(self) -> None:
        """With meters=0, only the battery entity remains."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        assert len(mesa.entities) == 1
        assert mesa.entities[0].entity_type == EntityType.BATTERY

    def test_entity_override_removes_batteries(self) -> None:
        """With batteries=0, only the meter entity remains."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"batteries": 0})
        assert len(mesa.entities) == 1
        assert mesa.entities[0].entity_type == EntityType.METER

    # -- Entity overrides affect database points ----------------------------

    def test_entity_override_meters_zero_removes_bi5000(self) -> None:
        """With meters=0, BI5000 should not be in the database."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        assert mesa.database.get_binary_input(5000) is None
        assert mesa.database.binary_input_count == 1  # only BI0

    def test_entity_override_meters_zero_removes_ai5000(self) -> None:
        """With meters=0, AI5000 should not be in the database."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0})
        assert mesa.database.get_analog_input(5000) is None
        assert mesa.database.analog_input_count == 1  # only AI0

    def test_entity_override_batteries_zero_removes_ao20000(self) -> None:
        """With batteries=0, AO20000 should not be in the AO store."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"batteries": 0})
        assert mesa.ao_store.get(20000) is None
        assert len(mesa.ao_store) == 2  # AO0 + AO249 (non-entity curve point)

    def test_entity_override_all_zero_keeps_only_scada(self) -> None:
        """With all entities at 0, only SCADA + non-entity points remain."""
        mesa = create_mesa_outstation(TEST_PROFILE, entity_overrides={"meters": 0, "batteries": 0})
        assert mesa.database.binary_input_count == 1  # BI0
        assert mesa.database.binary_output_count == 1  # BO0
        assert mesa.database.analog_input_count == 1  # AI0
        assert len(mesa.ao_store) == 2  # AO0 + AO249 (curve point has no entity)

    # -- Associated indices / command handler integration --------------------

    def test_associated_index_ao0_maps_to_ai0(self, mesa: MesaOutstation) -> None:
        """AO0 has associated_index='AI0' so direct_operate should mirror to AI0."""
        # Direct operate AO0 with value 42.0
        result = mesa.handler.direct_operate_analog_output(index=0, value=42.0)
        assert result.status.name == "SUCCESS"

        # AI0 should now reflect the value
        ai_point = mesa.database.get_analog_input(0)
        assert ai_point is not None
        assert ai_point.value == 42.0

    # -- Config parameters --------------------------------------------------

    def test_default_host_and_port(self, mesa: MesaOutstation) -> None:
        assert mesa.host == "0.0.0.0"
        assert mesa.port == 20000

    def test_custom_host_and_port(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, host="127.0.0.1", port=30000)
        assert mesa.host == "127.0.0.1"
        assert mesa.port == 30000

    def test_custom_address(self) -> None:
        mesa = create_mesa_outstation(TEST_PROFILE, address=10, master_address=5)
        assert mesa.outstation.config.address == 10
        assert mesa.outstation.config.master_address == 5

    # -- Profile accessible -------------------------------------------------

    def test_profile_is_set(self, mesa: MesaOutstation) -> None:
        assert mesa.profile is not None
        assert len(mesa.profile.analog_outputs.points) == 3  # AO0, AO20000, AO249


# ---------------------------------------------------------------------------
# _build_associated_indices unit tests
# ---------------------------------------------------------------------------


class TestBuildAssociatedIndices:
    """Direct unit tests for _build_associated_indices."""

    @pytest.fixture()
    def profile(self):
        return load_profile(TEST_PROFILE)

    def _make_db_with_ai(self, *ai_indices: int) -> Database:
        db = Database(config=DatabaseConfig(max_analog_inputs=len(ai_indices) + 5))
        for idx in ai_indices:
            db.add_analog_input(idx, AnalogInputConfig())
        return db

    def test_ao_with_valid_ai_target_maps_correctly(self, profile) -> None:
        """AO0 -> AI0 in the fixture: must map index 0 to ('AI', 0)."""
        db = self._make_db_with_ai(0, 5000)
        result = _build_associated_indices(profile, db)
        assert 0 in result
        point_type_str, target_index = result[0]
        assert point_type_str == PointType.ANALOG_INPUT.value
        assert target_index == 0

    def test_ao_without_associated_index_not_in_result(self, profile) -> None:
        """AO20000 has no associated_index: must not appear in the result."""
        db = self._make_db_with_ai(0, 5000)
        result = _build_associated_indices(profile, db)
        assert 20000 not in result

    def test_missing_target_ai_raises_value_error(self, profile) -> None:
        """AO0 has associated_index='AI0'; if AI0 is absent, must raise."""
        db = self._make_db_with_ai(5000)  # AI0 intentionally absent
        with pytest.raises(ValueError, match=r"AI0.*not in the database"):
            _build_associated_indices(profile, db)

    def test_malformed_associated_index_raises_value_error(self, profile) -> None:
        """A profile with an invalid associated_index string must raise clearly."""
        import json
        import tempfile
        from pathlib import Path

        bad_profile_data = json.loads(TEST_PROFILE.read_text())
        bad_profile_data["analog_outputs"]["points"][0]["associated_index"] = "XX999"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad_profile_data, f)
            bad_path = Path(f.name)

        bad_profile = load_profile(bad_path)
        db = self._make_db_with_ai(0)
        with pytest.raises(ValueError, match="malformed associated_index"):
            _build_associated_indices(bad_profile, db)
        bad_path.unlink()

    def test_excluded_ao_skipped_even_if_target_missing(self, profile) -> None:
        """When AO0 is excluded, missing AI0 must NOT raise."""
        db = self._make_db_with_ai(5000)  # AI0 absent; AO0 excluded
        excluded = {PointType.ANALOG_OUTPUT: {0}}
        result = _build_associated_indices(profile, db, excluded_indices=excluded)
        assert 0 not in result


# ---------------------------------------------------------------------------
# profile.py: missing 'supported' key raises ValueError
# ---------------------------------------------------------------------------


class TestProfileMissingSupportedKey:
    """Missing 'supported' key must raise, not silently drop the point."""

    def test_missing_supported_raises_value_error(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        bad_data = json.loads(TEST_PROFILE.read_text())
        # Remove 'supported' from the first binary output point
        del bad_data["binary_outputs"]["points"][0]["supported"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad_data, f)
            bad_path = Path(f.name)

        with pytest.raises(ValueError, match="supported"):
            load_profile(bad_path)
        bad_path.unlink()


# ---------------------------------------------------------------------------
# compute_excluded_indices: overrides={}
# ---------------------------------------------------------------------------


class TestComputeExcludedIndicesEmptyOverrides:
    """Explicit coverage: compute_excluded_indices with an empty dict."""

    def test_empty_overrides_excludes_nothing(self) -> None:
        from dnp3.mesa.entities import compute_excluded_indices

        profile = load_profile(TEST_PROFILE)
        result = compute_excluded_indices(profile, overrides={})
        # An empty overrides dict means max_counts is all zeros for any key
        # that appears in overrides; since we passed {}, none are present,
        # so every entity point uses 0 as the fallback from profile.entities.
        # Meter entity_number=1, profile.entities meters=1 -> 1 <= 1 -> not excluded.
        # Battery entity_number=1, profile.entities batteries=1 -> not excluded.
        assert PointType.BINARY_INPUT not in result or 5000 not in result.get(PointType.BINARY_INPUT, set())
        assert PointType.ANALOG_OUTPUT not in result or 20000 not in result.get(PointType.ANALOG_OUTPUT, set())
