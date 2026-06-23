"""Tests for MesaCommandHandler."""

from __future__ import annotations

import pytest

from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.database import AnalogInputConfig, BinaryInputConfig, BinaryOutputConfig, Database, DatabaseConfig
from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue
from dnp3.mesa.command_handler import MesaCommandHandler


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


class TestSelectAnalogOutput:
    """Tests for select_analog_output."""

    def test_valid_value_returns_success_no_store_update(
        self,
        handler: MesaCommandHandler,
        ao_store: AnalogOutputStore,
    ) -> None:
        result = handler.select_analog_output(index=0, value=50.0)
        assert result.status == CommandStatus.SUCCESS
        # Select is validation only — store should not change
        assert ao_store.get(0).value == 0.0

    def test_value_exceeds_max_returns_out_of_range(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=0, value=150.0)
        assert result.status == CommandStatus.OUT_OF_RANGE

    def test_nonexistent_index_returns_not_supported(self, handler: MesaCommandHandler) -> None:
        result = handler.select_analog_output(index=999, value=50.0)
        assert result.status == CommandStatus.NOT_SUPPORTED


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
