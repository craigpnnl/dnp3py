"""A successful group 41 command updates the analog output status point.

Clause 11.9.2.2: the status value represents the analog output value. After
DIRECT_OPERATE, DIRECT_OPERATE_NO_ACK or OPERATE of group 41 succeeds, the
outstation writes the commanded value into the Database's analog output
status point, so a later group 40 read returns what was commanded. SELECT
never writes.
"""

from __future__ import annotations

import struct

import pytest

from dnp3.application.builder import build_operate_request, build_select_request
from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, FunctionCode
from dnp3.core.flags import AnalogQuality
from dnp3.database import AnalogOutputConfig, Database
from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.outstation import Outstation
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import PeerId

MASTER = PeerId(source=3, connection=1)
SUCCESS = CommandStatus.SUCCESS
OUT_OF_RANGE = CommandStatus.OUT_OF_RANGE

# (variation, struct format, value) for g41v1 to g41v4; each survives its encoding exactly.
VARIATIONS = [
    pytest.param(1, "<i", 123456.0, id="g41v1-int32"),
    pytest.param(2, "<h", -300.0, id="g41v2-int16"),
    pytest.param(3, "<f", 12.5, id="g41v3-float32"),
    pytest.param(4, "<d", 0.1, id="g41v4-float64"),
]
FLOAT_VARIATIONS = [
    pytest.param(3, "<f", id="g41v3-float32"),
    pytest.param(4, "<d", id="g41v4-float64"),
]


class _RecordingHandler(DefaultCommandHandler):
    """Answers every g41 command with a configured status, SUCCESS by default."""

    def __init__(self) -> None:
        super().__init__()
        self.status = CommandStatus.SUCCESS

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        return CommandResult(status=self.status)

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        return CommandResult(status=self.status)

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        return CommandResult(status=self.status)


def _ao_block(variation: int, fmt: str, index: int, value: float, status: int = 0) -> ObjectBlock:
    """g41 block: count 1, then an index prefix, the encoded value and a status octet."""
    encoded = struct.pack(fmt, int(value) if fmt in {"<i", "<h"} else value)
    data = bytes([1]) + index.to_bytes(1, "little") + encoded + bytes([status])
    return ObjectBlock(header=ObjectHeader(group=41, variation=variation, qualifier=0x17), data=data)


def _direct_operate(outstation: Outstation, block: ObjectBlock, *, no_ack: bool = False) -> bytes:
    function = FunctionCode.DIRECT_OPERATE_NO_ACK if no_ack else FunctionCode.DIRECT_OPERATE
    request = RequestFragment(header=RequestHeader.build(function=function, seq=0), objects=(block,))
    responses = outstation.process_request(request.to_bytes(), peer=MASTER)
    if no_ack:
        assert responses == []
        return b""
    assert len(responses) == 1
    return responses[0].to_bytes()


def _select_then_operate(outstation: Outstation, block: ObjectBlock) -> bytes:
    outstation.process_request(build_select_request(objects=(block,), seq=0).to_bytes(), peer=MASTER)
    responses = outstation.process_request(build_operate_request(objects=(block,), seq=1).to_bytes(), peer=MASTER)
    assert len(responses) == 1
    return responses[0].to_bytes()


def _select_only(outstation: Outstation, block: ObjectBlock) -> None:
    responses = outstation.process_request(build_select_request(objects=(block,), seq=0).to_bytes(), peer=MASTER)
    assert len(responses) == 1


def _database_with_ao(index: int = 5, *, value: float = 0.0, track_commands: bool = True) -> Database:
    db = Database()
    db.add_analog_output(index, config=AnalogOutputConfig(track_commands=track_commands), value=value)
    return db


class TestDirectOperateUpdatesStatus:
    """SUCCESS from DIRECT_OPERATE writes the commanded value into the status point."""

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_success_stores_the_commanded_value(self, variation: int, fmt: str, value: float) -> None:
        db = _database_with_ao()
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(variation, fmt, 5, value)

        _direct_operate(outstation, block)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == value
        assert point.quality == AnalogQuality.ONLINE

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_no_ack_success_stores_the_commanded_value(self, variation: int, fmt: str, value: float) -> None:
        db = _database_with_ao()
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(variation, fmt, 5, value)

        _direct_operate(outstation, block, no_ack=True)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == value
        assert point.quality == AnalogQuality.ONLINE


class TestOperateUpdatesStatus:
    """SUCCESS from OPERATE (after a matching SELECT) writes the commanded value."""

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_select_then_operate_success_stores_the_commanded_value(
        self, variation: int, fmt: str, value: float
    ) -> None:
        db = _database_with_ao()
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(variation, fmt, 5, value)

        _select_then_operate(outstation, block)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == value
        assert point.quality == AnalogQuality.ONLINE


class TestNoWriteCases:
    """No write on a non-SUCCESS status, a missing point, an opted-out point, or SELECT."""

    @pytest.mark.parametrize("function", ["direct_operate", "operate"])
    def test_non_success_does_not_update_status(self, function: str) -> None:
        db = _database_with_ao(value=1.0)
        handler = _RecordingHandler()
        handler.status = OUT_OF_RANGE
        outstation = Outstation(database=db, handler=handler)
        block = _ao_block(3, "<f", 5, 99.0)

        if function == "direct_operate":
            _direct_operate(outstation, block)
        else:
            _select_then_operate(outstation, block)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 1.0

    @pytest.mark.parametrize("function", ["direct_operate", "operate"])
    def test_no_point_at_index_creates_none_and_raises_nothing(self, function: str) -> None:
        db = Database()
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(3, "<f", 5, 42.0)

        if function == "direct_operate":
            wire = _direct_operate(outstation, block)
        else:
            wire = _select_then_operate(outstation, block)

        assert db.get_analog_output(5) is None
        assert db.analog_output_count == 0
        assert wire[-1] == int(SUCCESS)

    @pytest.mark.parametrize("function", ["direct_operate", "operate"])
    def test_track_commands_false_does_not_update(self, function: str) -> None:
        db = _database_with_ao(value=7.0, track_commands=False)
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(3, "<f", 5, 99.0)

        if function == "direct_operate":
            _direct_operate(outstation, block)
        else:
            _select_then_operate(outstation, block)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 7.0

    def test_select_never_updates_status(self) -> None:
        db = _database_with_ao(value=3.0)
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(3, "<f", 5, 99.0)

        _select_only(outstation, block)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 3.0


class TestNanCommandIsRefused:
    """A commanded NaN is refused, logged once, and leaves the old status and response.

    OPERATE cannot carry a NaN through this assertion via SELECT-then-OPERATE:
    ``SelectState.matches_analog`` (state.py, unchanged here) compares the
    selected and operated values with ``==``, and NaN never equals NaN, so an
    OPERATE of a NaN value always answers NO_SELECT before reaching any
    handler. The three function codes share one tracking call on SUCCESS
    (``_track_ao_command``), so its OPERATE case is exercised directly.
    """

    @pytest.mark.parametrize(("variation", "fmt"), FLOAT_VARIATIONS)
    @pytest.mark.parametrize("no_ack", [False, True], ids=["direct-operate", "direct-operate-no-ack"])
    def test_nan_keeps_the_old_value_and_response(
        self, no_ack: bool, variation: int, fmt: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _database_with_ao(value=5.5)
        outstation = Outstation(database=db, handler=_RecordingHandler())
        block = _ao_block(variation, fmt, 5, float("nan"))

        with caplog.at_level("WARNING"):
            wire = _direct_operate(outstation, block, no_ack=no_ack)

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 5.5
        if not no_ack:
            assert wire[-1] == int(SUCCESS)
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "5" in warnings[0].getMessage()

    def test_operate_code_path_refuses_nan_the_same_way(self, caplog: pytest.LogCaptureFixture) -> None:
        db = _database_with_ao(value=5.5)
        outstation = Outstation(database=db, handler=_RecordingHandler())

        with caplog.at_level("WARNING"):
            outstation._track_ao_command(5, float("nan"))

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 5.5
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "5" in warnings[0].getMessage()


class TestMesaOutstationUnaffected:
    """P4: MESA keeps its AO status in AnalogOutputStore, not the Database, so this change is a no-op there."""

    def test_direct_operate_updates_the_ao_store_and_never_touches_the_database(self) -> None:
        db = Database()
        ao_store = AnalogOutputStore()
        ao_store.add(AnalogOutputValue(index=5, value=0.0, minimum=0.0, maximum=100.0))
        handler = MesaCommandHandler(database=db, ao_store=ao_store)
        outstation = Outstation(database=db, handler=handler)
        block = _ao_block(3, "<f", 5, 42.0)

        _direct_operate(outstation, block)

        stored = ao_store.get(5)
        assert stored is not None
        assert stored.value == 42.0
        assert db.get_analog_output(5) is None
        assert db.analog_output_count == 0
