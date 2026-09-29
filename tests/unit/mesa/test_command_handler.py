"""Tests for MesaCommandHandler."""

from __future__ import annotations

import math
import struct

import pytest

from dnp3.application.builder import build_direct_operate_request
from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.database import AnalogInputConfig, BinaryInputConfig, BinaryOutputConfig, Database, DatabaseConfig
from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.outstation import Outstation
from dnp3.outstation.handler import CommandResult
from dnp3.outstation.peer import PeerId


@pytest.fixture()
def database() -> Database:
    """Create a database with BO at 0, BI at 11, AI at 0."""
    db = Database(config=DatabaseConfig())
    db.add_binary_output(0, BinaryOutputConfig())
    db.add_binary_input(11, BinaryInputConfig())
    db.add_analog_input(0, AnalogInputConfig())
    return db


@pytest.fixture()
def ao_store() -> AnalogOutputStore:
    """Create an AO store with AO at index 0 (min=0, max=100)."""
    store = AnalogOutputStore()
    store.add(AnalogOutputValue(index=0, value=0.0, minimum=0.0, maximum=100.0))
    return store


@pytest.fixture()
def associated_indices() -> dict[int, tuple[str, int]]:
    """AO index 0 is associated with AI index 0."""
    return {0: ("AI", 0)}


@pytest.fixture()
def handler(
    database: Database,
    ao_store: AnalogOutputStore,
    associated_indices: dict[int, tuple[str, int]],
) -> MesaCommandHandler:
    return MesaCommandHandler(
        database=database,
        ao_store=ao_store,
        associated_indices=associated_indices,
    )


class TestDirectOperateBinaryOutput:
    """Tests for direct_operate_binary_output."""

    def test_latch_on_returns_success(self, handler: MesaCommandHandler, database: Database) -> None:
        result = handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.SUCCESS
        assert database.get_binary_output(0) is not None
        assert database.get_binary_output(0).value is True

    def test_latch_off_returns_success(self, handler: MesaCommandHandler, database: Database) -> None:
        # First set it on, then off
        handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        result = handler.direct_operate_binary_output(
            index=0,
            code=ControlCode.LATCH_OFF,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is False

    def test_nonexistent_index_returns_not_supported(self, handler: MesaCommandHandler) -> None:
        result = handler.direct_operate_binary_output(
            index=999,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED


class TestSelectBinaryOutput:
    """Tests for select_binary_output."""

    def test_existing_index_returns_success(self, handler: MesaCommandHandler) -> None:
        result = handler.select_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.SUCCESS

    def test_nonexistent_index_returns_not_supported(self, handler: MesaCommandHandler) -> None:
        result = handler.select_binary_output(
            index=999,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED


class TestOperateBinaryOutput:
    """Tests for operate_binary_output."""

    def test_latch_on_returns_success_and_updates_db(
        self,
        handler: MesaCommandHandler,
        database: Database,
    ) -> None:
        result = handler.operate_binary_output(
            index=0,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
            select_sequence=1,
        )
        assert result.status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is True


class TestDirectOperateAnalogOutput:
    """Tests for direct_operate_analog_output."""

    def test_valid_value_returns_success_and_updates_store_and_ai(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
        database: Database,
    ) -> None:
        result = handler.direct_operate_analog_output(index=0, value=50.0)
        assert result.status == CommandStatus.SUCCESS
        assert ao_store.get(0).value == 50.0
        assert database.get_analog_input(0).value == 50.0

    def test_value_exceeds_max_returns_out_of_range(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
    ) -> None:
        result = handler.direct_operate_analog_output(index=0, value=150.0)
        assert result.status == CommandStatus.OUT_OF_RANGE
        # Store should not have changed
        assert ao_store.get(0).value == 0.0

    def test_nonexistent_index_returns_not_supported(self, handler: MesaCommandHandler) -> None:
        result = handler.direct_operate_analog_output(index=999, value=50.0)
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_nan_returns_out_of_range_store_and_ai_unchanged(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
        database: Database,
    ) -> None:
        """NaN fails both range comparisons silently (#171): it is checked
        explicitly and answered the same way an out-of-range value already
        is, rather than reaching the store or the AI mirror at all."""
        result = handler.direct_operate_analog_output(index=0, value=math.nan)
        assert result.status == CommandStatus.OUT_OF_RANGE
        assert ao_store.get(0).value == 0.0
        assert database.get_analog_input(0).value == 0.0


class TestSelectAnalogOutput:
    """Tests for select_analog_output."""

    def test_valid_value_returns_success_no_store_update(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
    ) -> None:
        result = handler.select_analog_output(index=0, value=50.0)
        assert result.status == CommandStatus.SUCCESS
        # Select is validation only - store should not change
        assert ao_store.get(0).value == 0.0

    def test_value_exceeds_max_returns_out_of_range(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=0, value=150.0)
        assert result.status == CommandStatus.OUT_OF_RANGE

    def test_nonexistent_index_returns_not_supported(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=999, value=50.0)
        assert result.status == CommandStatus.NOT_SUPPORTED

    def test_nan_returns_out_of_range(self, handler: MesaCommandHandler, ao_store: AnalogOutputStore) -> None:
        result = handler.select_analog_output(index=0, value=math.nan)
        assert result.status == CommandStatus.OUT_OF_RANGE
        assert ao_store.get(0).value == 0.0


class TestOperateAnalogOutput:
    """Tests for operate_analog_output."""

    def test_valid_value_returns_success_and_updates_store_and_ai(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
        database: Database,
    ) -> None:
        result = handler.operate_analog_output(index=0, value=75.0, select_sequence=1)
        assert result.status == CommandStatus.SUCCESS
        assert ao_store.get(0).value == 75.0
        assert database.get_analog_input(0).value == 75.0

    def test_nan_returns_out_of_range_store_and_ai_unchanged(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
        database: Database,
    ) -> None:
        result = handler.operate_analog_output(index=0, value=math.nan, select_sequence=1)
        assert result.status == CommandStatus.OUT_OF_RANGE
        assert ao_store.get(0).value == 0.0
        assert database.get_analog_input(0).value == 0.0


class TestAnalogOutputStoreSetValueRefusesNaN:
    """AnalogOutputStore.set_value has its own NaN guard (#171), independent
    of MesaCommandHandler's validator: a direct caller of the store is
    covered too, not just the control-command path."""

    def test_set_value_nan_raises_and_store_unchanged(self) -> None:
        store = AnalogOutputStore()
        store.add(AnalogOutputValue(index=0, value=5.0, minimum=0.0, maximum=100.0))
        with pytest.raises(ValueError, match=r"nan"):
            store.set_value(0, math.nan)
        assert store.get(0).value == 5.0

    def test_set_value_negative_nan_raises(self) -> None:
        store = AnalogOutputStore()
        store.add(AnalogOutputValue(index=0, value=5.0, minimum=0.0, maximum=100.0))
        with pytest.raises(ValueError, match=r"nan"):
            store.set_value(0, -math.nan)
        assert store.get(0).value == 5.0


class TestOperateBinaryOutputLatchOff:
    """Explicit coverage for LATCH_OFF path in operate_binary_output."""

    def test_latch_off_sets_value_false(
        self,
        handler: MesaCommandHandler,
        database: Database,
    ) -> None:
        # Prime to True first
        handler.operate_binary_output(
            index=0, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0, select_sequence=1
        )
        assert database.get_binary_output(0).value is True

        result = handler.operate_binary_output(
            index=0, code=ControlCode.LATCH_OFF, count=1, on_time=0, off_time=0, select_sequence=1
        )
        assert result.status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is False


class TestSelectAnalogOutputBoundaries:
    """Exact min/max boundary acceptance on select_analog_output."""

    def test_select_at_minimum_returns_success(self, handler: MesaCommandHandler) -> None:
        """Value exactly at minimum (0.0) must be valid."""
        result = handler.select_analog_output(index=0, value=0.0)
        assert result.status == CommandStatus.SUCCESS

    def test_select_at_maximum_returns_success(self, handler: MesaCommandHandler) -> None:
        """Value exactly at maximum (100.0) must be valid."""
        result = handler.select_analog_output(index=0, value=100.0)
        assert result.status == CommandStatus.SUCCESS

    def test_select_below_minimum_returns_out_of_range(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=0, value=-0.001)
        assert result.status == CommandStatus.OUT_OF_RANGE

    def test_select_above_maximum_returns_out_of_range(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=0, value=100.001)
        assert result.status == CommandStatus.OUT_OF_RANGE


class TestControlCodeElseBranch:
    """The else branch (a code the handler does not carry out): NOT_SUPPORTED, no state change."""

    @pytest.mark.parametrize("initial", [False, True])
    def test_unrecognised_control_code_returns_not_supported_no_change(
        self,
        handler: MesaCommandHandler,
        database: Database,
        initial: bool,
    ) -> None:
        database.update_binary_output(0, value=initial)
        result = handler.direct_operate_binary_output(
            index=0,
            code=ControlCode(0xC1),
            count=1,
            on_time=0,
            off_time=0,
        )
        assert result.status == CommandStatus.NOT_SUPPORTED
        assert database.get_binary_output(0).value is initial


def _operate(
    handler: MesaCommandHandler, function: str, octet: int, *, count: int = 1, on: int = 0, off: int = 0
) -> CommandResult:
    """Run one binary-output command through OPERATE or DIRECT_OPERATE."""
    code = ControlCode(octet)
    if function == "operate":
        return handler.operate_binary_output(
            index=0, code=code, count=count, on_time=on, off_time=off, select_sequence=1
        )
    return handler.direct_operate_binary_output(index=0, code=code, count=count, on_time=on, off_time=off)


_EXECUTE = pytest.mark.parametrize("function", ["operate", "direct_operate"])


class TestBinaryOutputLatchSemantics:
    """Every binary output behaves as latched (IEEE 1815.2-2025 5.6.2), decided from the whole octet."""

    @_EXECUTE
    @pytest.mark.parametrize("octet", [0x03, 0x41, 0x01], ids=["LATCH_ON", "CLOSE_PULSE_ON", "PULSE_ON"])
    def test_on_codes_set_output_on(
        self, handler: MesaCommandHandler, database: Database, function: str, octet: int
    ) -> None:
        database.update_binary_output(0, value=False)
        assert _operate(handler, function, octet).status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is True

    @_EXECUTE
    @pytest.mark.parametrize("octet", [0x04, 0x81, 0x02], ids=["LATCH_OFF", "TRIP_PULSE_ON", "PULSE_OFF"])
    def test_off_codes_set_output_off(
        self, handler: MesaCommandHandler, database: Database, function: str, octet: int
    ) -> None:
        database.update_binary_output(0, value=True)
        assert _operate(handler, function, octet).status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is False

    @_EXECUTE
    @pytest.mark.parametrize("initial", [False, True])
    def test_nul_succeeds_without_change(
        self, handler: MesaCommandHandler, database: Database, function: str, initial: bool
    ) -> None:
        database.update_binary_output(0, value=initial)
        assert _operate(handler, function, 0x00).status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is initial

    @_EXECUTE
    @pytest.mark.parametrize("initial", [False, True])
    @pytest.mark.parametrize(
        "octet",
        [0x23, 0x24, 0x20, 0x21, 0x61, 0xA1, 0x13, 0x14, 0x10, 0xC0, 0xC1, 0xC3],
        ids=[
            "CLEAR_LATCH_ON",
            "CLEAR_LATCH_OFF",
            "CLEAR_NUL",
            "CLEAR_PULSE_ON",
            "CLEAR_CLOSE",
            "CLEAR_TRIP",
            "QUEUE_LATCH_ON",
            "QUEUE_LATCH_OFF",
            "QUEUE_NUL",
            "RESERVED_NUL",
            "RESERVED_PULSE_ON",
            "RESERVED_LATCH_ON",
        ],
    )
    def test_clear_queue_and_reserved_not_supported(
        self, handler: MesaCommandHandler, database: Database, function: str, initial: bool, octet: int
    ) -> None:
        database.update_binary_output(0, value=initial)
        assert _operate(handler, function, octet).status == CommandStatus.NOT_SUPPORTED
        assert database.get_binary_output(0).value is initial

    @_EXECUTE
    @pytest.mark.parametrize(
        ("octet", "initial", "status"),
        [
            (0x03, False, CommandStatus.SUCCESS),
            (0x81, True, CommandStatus.SUCCESS),
            (0x00, False, CommandStatus.SUCCESS),
            (0x23, False, CommandStatus.NOT_SUPPORTED),
        ],
    )
    def test_count_zero_changes_nothing_and_keeps_status(
        self,
        *,
        handler: MesaCommandHandler,
        database: Database,
        function: str,
        octet: int,
        initial: bool,
        status: CommandStatus,
    ) -> None:
        database.update_binary_output(0, value=initial)
        assert _operate(handler, function, octet, count=0).status == status
        assert database.get_binary_output(0).value is initial

    @_EXECUTE
    @pytest.mark.parametrize(("octet", "initial"), [(0x03, False), (0x81, True), (0x00, False)])
    @pytest.mark.parametrize("count", [2, 255])
    def test_count_above_one_not_supported(
        self,
        *,
        handler: MesaCommandHandler,
        database: Database,
        function: str,
        octet: int,
        initial: bool,
        count: int,
    ) -> None:
        database.update_binary_output(0, value=initial)
        assert _operate(handler, function, octet, count=count).status == CommandStatus.NOT_SUPPORTED
        assert database.get_binary_output(0).value is initial

    @_EXECUTE
    def test_pulse_times_ignored(self, handler: MesaCommandHandler, database: Database, function: str) -> None:
        """A PULSE_ON with on and off times latches ON and does not pulse back."""
        database.update_binary_output(0, value=False)
        assert _operate(handler, function, 0x01, on=5000, off=100).status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is True


class TestNonInteroperableTripCloseCombinations:
    """Trip-Close with any Op Type other than PULSE_ON is not carried out."""

    @pytest.mark.parametrize("function", ["select", "operate", "direct_operate"])
    @pytest.mark.parametrize("initial", [False, True])
    @pytest.mark.parametrize("octet", [0x40, 0x43, 0x80, 0x82, 0x84, 0x42, 0x44, 0x83])
    def test_not_supported_and_unchanged(
        self, handler: MesaCommandHandler, database: Database, function: str, initial: bool, octet: int
    ) -> None:
        database.update_binary_output(0, value=initial)
        if function == "select":
            result = handler.select_binary_output(index=0, code=ControlCode(octet), count=1, on_time=0, off_time=0)
        else:
            result = _operate(handler, function, octet)
        assert result.status == CommandStatus.NOT_SUPPORTED
        assert database.get_binary_output(0).value is initial


class TestSelectMatchesOperate:
    """SELECT refuses exactly what OPERATE refuses, and never changes the output."""

    @pytest.mark.parametrize("initial", [False, True])
    def test_select_status_equals_operate_status(self, database: Database, initial: bool) -> None:
        for octet in range(256):
            if octet & 0x0F > 4:
                continue
            for count in (0, 1, 2):
                select_db = Database(config=DatabaseConfig())
                select_db.add_binary_output(0, BinaryOutputConfig())
                select_db.update_binary_output(0, value=initial)
                selector = MesaCommandHandler(database=select_db, ao_store=AnalogOutputStore())
                operate_db = Database(config=DatabaseConfig())
                operate_db.add_binary_output(0, BinaryOutputConfig())
                operate_db.update_binary_output(0, value=initial)
                operator = MesaCommandHandler(database=operate_db, ao_store=AnalogOutputStore())

                selected = selector.select_binary_output(
                    index=0, code=ControlCode(octet), count=count, on_time=0, off_time=0
                )
                operated = _operate(operator, "operate", octet, count=count)

                assert selected.status == operated.status, f"octet 0x{octet:02X} count {count}"
                assert select_db.get_binary_output(0).value is initial, f"SELECT changed output: 0x{octet:02X}"

    @pytest.mark.parametrize("octet", [0x81, 0x41, 0x01, 0x02])
    def test_select_accepts_supported_code(self, handler: MesaCommandHandler, database: Database, octet: int) -> None:
        database.update_binary_output(0, value=False)
        result = handler.select_binary_output(index=0, code=ControlCode(octet), count=1, on_time=0, off_time=0)
        assert result.status == CommandStatus.SUCCESS
        assert database.get_binary_output(0).value is False

    @pytest.mark.parametrize("octet", [0x23, 0x24, 0x13, 0xC1])
    def test_select_refuses_unsupported_code(self, handler: MesaCommandHandler, database: Database, octet: int) -> None:
        database.update_binary_output(0, value=False)
        result = handler.select_binary_output(index=0, code=ControlCode(octet), count=1, on_time=0, off_time=0)
        assert result.status == CommandStatus.NOT_SUPPORTED
        assert database.get_binary_output(0).value is False


def _ao_block(points: list[tuple[int, float]]) -> ObjectBlock:
    """g41v3 (float32) block carrying every (index, value) pair given, in order."""
    data = bytes([len(points)])
    for index, value in points:
        data += index.to_bytes(1, "little") + struct.pack("<f", value) + bytes([0])
    return ObjectBlock(header=ObjectHeader(group=41, variation=3, qualifier=0x17), data=data)


class TestOutstationDirectOperateNaNAmongValidPoints:
    """A NaN point does not stop the block: #46's per-point guard only stops
    later handler calls on a raise, and OUT_OF_RANGE is a returned status,
    not a raise (#171)."""

    def _outstation(self) -> tuple[Outstation, AnalogOutputStore, Database]:
        db = Database(config=DatabaseConfig())
        db.add_analog_input(0, AnalogInputConfig())
        db.add_analog_input(1, AnalogInputConfig())
        store = AnalogOutputStore()
        store.add(AnalogOutputValue(index=0, value=0.0, minimum=0.0, maximum=100.0))
        store.add(AnalogOutputValue(index=1, value=0.0, minimum=0.0, maximum=100.0))
        handler = MesaCommandHandler(
            database=db,
            ao_store=store,
            associated_indices={0: ("AI", 0), 1: ("AI", 1)},
        )
        return Outstation(database=db, handler=handler), store, db

    def test_nan_point_out_of_range_valid_point_still_operated(self) -> None:
        outstation, store, db = self._outstation()
        request = build_direct_operate_request(objects=(_ao_block([(0, math.nan), (1, 42.0)]),), seq=0)
        responses = outstation.process_request(request.to_bytes(), peer=PeerId(source=3, connection=1))

        assert len(responses) == 1
        echoed = responses[0].objects[0]
        # qualifier 0x17: data[0]=count, then per point: 1-byte index, 4-byte
        # float32, 1-byte status (6 bytes per point). Status sits at offset
        # 5 within each point's 6 bytes.
        point_size = 6
        status0 = echoed.data[1 + 5]
        status1 = echoed.data[1 + point_size + 5]
        assert status0 == int(CommandStatus.OUT_OF_RANGE)
        assert status1 == int(CommandStatus.SUCCESS)

        ao0 = store.get(0)
        ao1 = store.get(1)
        ai0 = db.get_analog_input(0)
        ai1 = db.get_analog_input(1)
        assert ao0 is not None
        assert ao1 is not None
        assert ai0 is not None
        assert ai1 is not None
        assert ao0.value == 0.0, "the NaN point's store value must not change"
        assert ao1.value == 42.0, "the valid point must still be operated"
        assert ai0.value == 0.0
        assert ai1.value == 42.0
