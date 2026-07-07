"""Integration tests for the MESA outstation against the bundled full.json.

These exercise the loader, database builder, entity model, and command handler
end to end on the real PICS profile. Point counts are asserted exactly so a
mesa-tool schema or point-map change breaks loudly.
"""

from __future__ import annotations

import struct
import typing
from pathlib import Path

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.entities import EntityType, build_entities
from dnp3.mesa.outstation import MesaOutstation, create_mesa_outstation
from dnp3.mesa.profile import PicsProfile, PointType, load_profile
from dnp3.outstation.outstation import Outstation

PROFILE_PATH = Path(__file__).parents[2] / "src" / "dnp3" / "mesa" / "data" / "profiles" / "full.json"


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
        # All 8 CTR points are registered; all 8 have frozen_counter_exists=True.
        assert database.counter_count == 8
        assert database.frozen_counter_count == 8


class TestScheduleAndCurveRegistration:
    """Schedule AI points register at their absolute indices with scaled
    values, same as curves (the base-only-registration trap covers both
    functional sub-groups equally). Indices and values below are read
    verbatim from src/dnp3/mesa/data/profiles/full.json."""

    def test_schedule_bc_header_and_array_points_present(self, mesa_outstation: MesaOutstation) -> None:
        # schedules_bc[0]: identity=2002 (header), values[0]=2013 (array).
        for index in (2002, 2013):
            assert mesa_outstation.database.get_analog_input(index) is not None, f"AI{index} missing"

    def test_schedule_header_and_array_points_present(self, mesa_outstation: MesaOutstation) -> None:
        # schedules[0]: identity=3001 (header), values[0]=3015 (array).
        for index in (3001, 3015):
            assert mesa_outstation.database.get_analog_input(index) is not None, f"AI{index} missing"

    def test_schedule_bc_identity_scaled_value(self, mesa_outstation: MesaOutstation) -> None:
        # schedules_bc[0].identity: value 1.0, multiplier 1.0, offset 0.0 -> raw 1.
        point = mesa_outstation.database.get_analog_input(2002)
        assert point is not None
        assert point.value == 1

    def test_schedule_identity_scaled_value(self, mesa_outstation: MesaOutstation) -> None:
        # schedules[0].identity: value 1.0, multiplier 1.0, offset 0.0 -> raw 1.
        point = mesa_outstation.database.get_analog_input(3001)
        assert point is not None
        assert point.value == 1

    def test_schedule_bc_array_point_scaled_value(self, mesa_outstation: MesaOutstation) -> None:
        # schedules_bc[0].values[0] (AI2013): engineering 1.0, multiplier 1.0,
        # offset 0.0 -> transmission = round((1.0 - 0.0) / 1.0) = 1. Every one
        # of the four schedules_bc instances shares this multiplexed index and
        # the same engineering value in full.json; first-wins dedup registers
        # schedules_bc[0]. Verified by scanning the whole profile: no
        # schedules_bc point (header or array) carries a non-identity
        # multiplier/offset, so 1.0/0.0 is the only scaling this profile
        # exercises for this sub-group.
        point = mesa_outstation.database.get_analog_input(2013)
        assert point is not None
        assert point.value == 1

    def test_schedule_array_point_scaled_value(self, mesa_outstation: MesaOutstation) -> None:
        # schedules[0].values[...] (AI3019): engineering 9.0, multiplier 1.0,
        # offset 0.0 -> transmission = round((9.0 - 0.0) / 1.0) = 9. Chosen
        # over AI3015 (values[0], engineering 1.0, identical to the ubiquitous
        # "1" seen elsewhere in this profile's schedule points) so a
        # wrong-index or wrong-field read of the array would not silently
        # coincide with the expected value.
        point = mesa_outstation.database.get_analog_input(3019)
        assert point is not None
        assert point.value == 9

    def test_curve_selector_ao245_mirrors_to_curve_type_ai329(self) -> None:
        # AO245 -> AI329 is the curve-edit selector cited in the DNP-022 plan
        # (Section 5.4): AI329 is the curve_type header point shared by all 4
        # curves (multiplexed onto one DNP3 index). The plain AO->AI mirror
        # must resolve for it: before PR1's full curve registration, AI329
        # would not exist in the database and this write would be a silent
        # no-op skip rather than a mirrored write.
        #
        # A fresh outstation is built here (not the module-scoped
        # ``mesa_outstation`` fixture) because this test mutates state via a
        # command write and must not leak that mutation into other tests
        # sharing the fixture.
        mesa = create_mesa_outstation(PROFILE_PATH)
        result = mesa.handler.direct_operate_analog_output(index=245, value=5)
        assert result.status == CommandStatus.SUCCESS
        ai_point = mesa.database.get_analog_input(329)
        assert ai_point is not None
        assert ai_point.value == 5


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


def _decode_static_counter_blocks(responses: list, group: int) -> dict[int, int]:
    """Decode static counter or frozen-counter objects from a list of response fragments.

    For static blocks the ObjectBlock.data layout is:
      [start_bytes] [stop_bytes] [5 bytes per point: 1 flag + 4 value LE unsigned]

    The qualifier code determines the range-field width:
      0x00: 1-byte start + 1-byte stop (indices 0-255)
      0x01: 2-byte start + 2-byte stop (indices 0-65535)
      0x02: 4-byte start + 4-byte stop (wider, not used here)

    Returns a dict mapping {index: value}.
    """
    result: dict[int, int] = {}
    for frag in responses:
        for obj in frag.objects:
            if obj.header.group != group:
                continue
            qualifier = obj.header.qualifier
            data = obj.data
            if qualifier == 0x00:
                # 1-byte start/stop
                start = data[0]
                stop = data[1]
                payload = data[2:]
            elif qualifier == 0x01:
                # 2-byte start/stop (little-endian)
                start = struct.unpack_from("<H", data, 0)[0]
                stop = struct.unpack_from("<H", data, 2)[0]
                payload = data[4:]
            else:
                continue  # unsupported qualifier for this helper
            n_points = stop - start + 1
            assert len(payload) == n_points * 5, (
                f"group {group} block start={start} stop={stop}: expected "
                f"{n_points * 5} payload bytes, got {len(payload)}"
            )
            for i in range(n_points):
                _flags = payload[i * 5]
                value = struct.unpack_from("<I", payload, i * 5 + 1)[0]
                result[start + i] = value
    return result


class TestCounterWireEmission:
    """Verify that counters and frozen counters are served on the wire.

    Tests the full path: build_database(profile) -> Outstation(database=db) ->
    process_request(integrity poll) -> assert g20v1 counter and g21v1 frozen
    counter objects present with correct indices and initial zero values.

    full.json has 8 CTR points: indices 0, 1, 2, 3, 5000, 5001, 5002, 5003.
    All 8 have frozen_counter_exists=True. Initial values are 0 (PicsProfile
    carries no initial counter reading).
    """

    EXPECTED_CTR_INDICES: typing.ClassVar[frozenset[int]] = frozenset({0, 1, 2, 3, 5000, 5001, 5002, 5003})

    @pytest.fixture()
    def integrity_responses(self, profile: PicsProfile) -> list:
        database, _ = build_database(profile)
        outstation = Outstation(database=database)
        request = build_integrity_poll()
        return outstation.process_request(request.to_bytes())

    def test_integrity_poll_produces_response(self, integrity_responses: list) -> None:
        assert len(integrity_responses) > 0

    def test_counter_group_present(self, integrity_responses: list) -> None:
        """g20v1 counter objects are present in the integrity poll response."""
        ctr_map = _decode_static_counter_blocks(integrity_responses, group=20)
        assert ctr_map, "No g20v1 counter objects found in integrity poll response"

    def test_counter_indices_match_profile(self, integrity_responses: list) -> None:
        """All 8 CTR point indices from the profile appear in the g20v1 response."""
        ctr_map = _decode_static_counter_blocks(integrity_responses, group=20)
        assert set(ctr_map.keys()) == self.EXPECTED_CTR_INDICES, (
            f"Counter indices mismatch: got {set(ctr_map.keys())}, expected {self.EXPECTED_CTR_INDICES}"
        )

    def test_counter_initial_values_zero(self, integrity_responses: list) -> None:
        """All counter initial values are 0 (no initial reading in PicsProfile)."""
        ctr_map = _decode_static_counter_blocks(integrity_responses, group=20)
        for idx in self.EXPECTED_CTR_INDICES:
            assert ctr_map[idx] == 0, f"Counter index {idx}: expected value 0, got {ctr_map[idx]}"

    def test_frozen_counter_group_present(self, integrity_responses: list) -> None:
        """g21v1 frozen counter objects are present in the integrity poll response."""
        fc_map = _decode_static_counter_blocks(integrity_responses, group=21)
        assert fc_map, "No g21v1 frozen counter objects found in integrity poll response"

    def test_frozen_counter_indices_match_profile(self, integrity_responses: list) -> None:
        """All 8 CTR points with frozen_counter_exists=True appear in g21v1 response."""
        fc_map = _decode_static_counter_blocks(integrity_responses, group=21)
        assert set(fc_map.keys()) == self.EXPECTED_CTR_INDICES, (
            f"Frozen counter indices mismatch: got {set(fc_map.keys())}, expected {self.EXPECTED_CTR_INDICES}"
        )

    def test_frozen_counter_initial_values_zero(self, integrity_responses: list) -> None:
        """All frozen counter initial values are 0."""
        fc_map = _decode_static_counter_blocks(integrity_responses, group=21)
        for idx in self.EXPECTED_CTR_INDICES:
            assert fc_map[idx] == 0, f"Frozen counter index {idx}: expected value 0, got {fc_map[idx]}"

    def test_counter_nonzero_value_round_trips(self, profile: PicsProfile) -> None:
        """update_counter(value=12345) is reflected in the g20v1 static response.

        Verifies the full path: database mutation -> outstation static serve ->
        integrity poll wire bytes -> decoded value == 12345 at the expected index.
        """
        database, _ = build_database(profile)
        # Update index 0 to a well-known non-zero value.
        database.update_counter(index=0, value=12345)
        outstation = Outstation(database=database)
        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        ctr_map = _decode_static_counter_blocks(responses, group=20)
        assert ctr_map.get(0) == 12345, f"Counter index 0: expected 12345 after update_counter, got {ctr_map.get(0)}"
        # All other indices remain 0 (no spurious mutation).
        for idx in self.EXPECTED_CTR_INDICES - {0}:
            assert ctr_map[idx] == 0, f"Counter index {idx}: expected 0 (no mutation), got {ctr_map[idx]}"

    def test_frozen_counter_nonzero_value_round_trips(self, profile: PicsProfile) -> None:
        """freeze_counter after update_counter(value=67890) appears in g21v1 response.

        Verifies the full path: counter update -> freeze -> outstation static
        serve -> integrity poll wire bytes -> decoded frozen value == 67890 at
        the expected index.
        """
        database, _ = build_database(profile)
        # full.json CTR points all have frozen_counter_exists=True so index 0 has
        # both a counter and a frozen counter in the database.
        database.update_counter(index=0, value=67890)
        database.freeze_counter(counter_index=0)
        outstation = Outstation(database=database)
        request = build_integrity_poll()
        responses = outstation.process_request(request.to_bytes())

        fc_map = _decode_static_counter_blocks(responses, group=21)
        assert fc_map.get(0) == 67890, f"Frozen counter index 0: expected 67890 after freeze, got {fc_map.get(0)}"
        # All other frozen counter indices remain 0.
        for idx in self.EXPECTED_CTR_INDICES - {0}:
            assert fc_map[idx] == 0, f"Frozen counter index {idx}: expected 0 (not frozen), got {fc_map[idx]}"
