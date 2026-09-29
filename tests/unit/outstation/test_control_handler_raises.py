"""Fix #46, part 2: a raise inside a control handler stops the request at that point.

A raise, or a return that is not a valid CommandResult, gives that point's
status UNDEFINED (127, Table 11-7) and stops every later point in the request
from reaching the handler at all, across blocks (IEEE 1815-2012 4.4.4.3 Rule
5). The response still echoes every object, in wire order, with its own
status (Rule 7), so the master learns exactly which points ran. Part 1
(#155) answers every other request path with a null response; this file
covers only the control paths that part 1 left as a whole-request failure.
"""

from __future__ import annotations

import logging

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database import Database
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandHandler, CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)

_UNDEFINED = 0x7F  # CommandStatus.UNDEFINED (127), Table 11-7.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")  # LATCH_ON, count 1, on/off 0, status 0.
_CROB_RECORD_SIZE = 12  # 1-byte index + 11-byte body.
_AO_RECORD_SIZE = 4  # g41v2 (16-bit signed): 1-byte index + 2-byte value + 1-byte status.


def _outstation(handler: CommandHandler, *, database: Database | None = None) -> Outstation:
    """An Outstation with NEED_TIME cleared, so a fresh IIN1 is DEVICE_RESTART (0x80) alone."""
    config = OutstationConfig(time_sync_required=False)
    return Outstation(config=config, handler=handler, database=database or Database())


def _crob_block(*indices: int) -> ObjectBlock:
    """A well-formed g12v1 block, qualifier 0x17, one object per index, in wire order."""
    header = ObjectHeader(group=12, variation=1, qualifier=0x17)
    data = bytes([len(indices)])
    for index in indices:
        data += bytes([index]) + _CROB_BODY
    return ObjectBlock(header=header, data=data)


def _ao_block(*entries: tuple[int, int]) -> ObjectBlock:
    """A well-formed g41v2 block, qualifier 0x17, one (index, value) object per entry."""
    header = ObjectHeader(group=41, variation=2, qualifier=0x17)
    data = bytes([len(entries)])
    for index, value in entries:
        data += bytes([index]) + value.to_bytes(2, "little", signed=True) + bytes([0])
    return ObjectBlock(header=header, data=data)


def _request(function: FunctionCode, *objects: ObjectBlock, seq: int = 0) -> RequestFragment:
    return RequestFragment(header=RequestHeader.build(function=function, seq=seq), objects=objects)


def _record_size(block: ObjectBlock) -> int:
    return _CROB_RECORD_SIZE if block.header.group == 12 else _AO_RECORD_SIZE


def _expected_echo(request: RequestFragment, block_statuses: list[list[int]], *, iin2: int = 0) -> bytes:
    """Expected response bytes: each block's object octets with its point statuses set.

    ``block_statuses[i]`` holds one status per object of ``request.objects[i]``, in
    wire order (IEEE 1815-2012 4.4.4.3 Rule 7 and Rule 8).
    """
    seq = request.header.control.seq
    body = bytearray()
    for block, statuses in zip(request.objects, block_statuses, strict=True):
        record_size = _record_size(block)
        echoed = bytearray(block.to_bytes())
        for position, status in enumerate(statuses):
            offset = 3 + 1 + position * record_size + (record_size - 1)  # header(3) + count(1) + record
            echoed[offset] = status
        body += echoed
    return bytes([0xC0 | seq, 0x81, 0x80, iin2]) + bytes(body)


def _statuses(response: ResponseFragment, *, count: int) -> list[CommandStatus]:
    """The CommandStatus of each object in the response's single CROB block, in wire order."""
    data = response.objects[0].data
    return [
        CommandStatus(data[1 + position * _CROB_RECORD_SIZE + (_CROB_RECORD_SIZE - 1)]) for position in range(count)
    ]


class _CallTrackingHandler(DefaultCommandHandler):
    """Records every control call in order; a configured (method, index) raises once."""

    def __init__(self, *, raise_on: dict[str, set[int]] | None = None, exc: type[BaseException] = ValueError) -> None:
        super().__init__()
        self.calls: list[tuple[str, int]] = []
        self.raise_on = raise_on or {}
        self.exc = exc

    def _record(self, method: str, index: int) -> None:
        self.calls.append((method, index))
        indices = self.raise_on.get(method)
        if indices is not None and index in indices:
            indices.discard(index)
            raise self.exc(f"boom: {method} {index}")

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self._record("select_binary_output", index)
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self._record("operate_binary_output", index)
        return CommandResult.success()

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self._record("direct_operate_binary_output", index)
        return CommandResult.success()

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        self._record("select_analog_output", index)
        return CommandResult.success()

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        self._record("operate_analog_output", index)
        return CommandResult.success()

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        self._record("direct_operate_analog_output", index)
        return CommandResult.success()


class TestDirectOperateStopsAfterRaise:
    """DIRECT_OPERATE: a raise stops every later point, in the same block and later ones."""

    def test_two_points_raise_on_second_calls_both_and_echoes_undefined(self) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {2}})
        outstation = _outstation(handler)

        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(1, 2), seq=1)
        responses = outstation.process_request(request.to_bytes())

        assert handler.calls == [("direct_operate_binary_output", 1), ("direct_operate_binary_output", 2)]
        assert len(responses) == 1
        assert responses[0].to_bytes() == _expected_echo(request, [[0, _UNDEFINED]])
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin

    def test_new_sequence_retry_of_the_stopped_point_alone_calls_only_that_point(self) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {2}})
        outstation = _outstation(handler)
        outstation.process_request(_request(FunctionCode.DIRECT_OPERATE, _crob_block(1, 2), seq=1).to_bytes())

        outstation.process_request(_request(FunctionCode.DIRECT_OPERATE, _crob_block(2), seq=2).to_bytes())

        assert handler.calls == [
            ("direct_operate_binary_output", 1),
            ("direct_operate_binary_output", 2),
            ("direct_operate_binary_output", 2),
        ]

    def test_three_points_raise_on_second_stops_the_third(self) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {2}})
        outstation = _outstation(handler)

        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(1, 2, 3), seq=1)
        responses = outstation.process_request(request.to_bytes())

        assert handler.calls == [("direct_operate_binary_output", 1), ("direct_operate_binary_output", 2)]
        assert responses[0].to_bytes() == _expected_echo(request, [[0, _UNDEFINED, _UNDEFINED]])

    def test_raise_in_first_block_stops_the_second_block_entirely(self) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {1}})
        outstation = _outstation(handler)
        outstation.database.add_analog_output(5)

        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(1), _ao_block((5, 10)), seq=1)
        responses = outstation.process_request(request.to_bytes())

        assert handler.calls == [("direct_operate_binary_output", 1)]
        assert ("direct_operate_analog_output", 5) not in handler.calls
        assert responses[0].to_bytes() == _expected_echo(request, [[_UNDEFINED], [_UNDEFINED]])


class TestSelectStopsAfterRaise:
    """SELECT: a raise cancels the whole selection (Rule 3), including points that already armed."""

    def test_two_points_raise_on_second_echoes_undefined(self) -> None:
        handler = _CallTrackingHandler(raise_on={"select_binary_output": {2}})
        outstation = _outstation(handler)

        request = _request(FunctionCode.SELECT, _crob_block(1, 2), seq=4)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert handler.calls == [("select_binary_output", 1), ("select_binary_output", 2)]
        assert responses[0].to_bytes() == _expected_echo(request, [[0, _UNDEFINED]])

    def test_same_seq_retry_repeats_the_response_with_no_new_calls(self) -> None:
        handler = _CallTrackingHandler(raise_on={"select_binary_output": {2}})
        outstation = _outstation(handler)
        request = _request(FunctionCode.SELECT, _crob_block(1, 2), seq=4)
        first = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        retry = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert retry[0].to_bytes() == first[0].to_bytes()
        assert handler.calls == [("select_binary_output", 1), ("select_binary_output", 2)]

    def test_operate_at_next_seq_answers_no_select_for_both_points_with_zero_calls(self) -> None:
        handler = _CallTrackingHandler(raise_on={"select_binary_output": {2}})
        outstation = _outstation(handler)
        outstation.process_request(_request(FunctionCode.SELECT, _crob_block(1, 2), seq=4).to_bytes(), peer=MASTER_A)

        operate_responses = outstation.process_request(
            _request(FunctionCode.OPERATE, _crob_block(1, 2), seq=5).to_bytes(), peer=MASTER_A
        )

        assert _statuses(operate_responses[0], count=2) == [CommandStatus.NO_SELECT, CommandStatus.NO_SELECT]
        assert ("operate_binary_output", 1) not in handler.calls
        assert ("operate_binary_output", 2) not in handler.calls

    def test_a_second_peer_can_select_both_points_after_the_cancellation(self) -> None:
        handler = _CallTrackingHandler(raise_on={"select_binary_output": {2}})
        outstation = _outstation(handler)
        outstation.process_request(_request(FunctionCode.SELECT, _crob_block(1, 2), seq=4).to_bytes(), peer=MASTER_A)

        responses = outstation.process_request(
            _request(FunctionCode.SELECT, _crob_block(1, 2), seq=1).to_bytes(), peer=MASTER_B
        )

        assert _statuses(responses[0], count=2) == [CommandStatus.SUCCESS, CommandStatus.SUCCESS]


class TestOperateStopsAfterRaise:
    """OPERATE: a raise stops later points; the selection still ends (existing finally)."""

    def test_two_points_raise_on_first_stops_the_second_and_ends_the_selection(self) -> None:
        handler = _CallTrackingHandler(raise_on={"operate_binary_output": {1}})
        outstation = _outstation(handler)
        outstation.process_request(_request(FunctionCode.SELECT, _crob_block(1, 2), seq=4).to_bytes(), peer=MASTER_A)

        request = _request(FunctionCode.OPERATE, _crob_block(1, 2), seq=5)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert handler.calls[-1] == ("operate_binary_output", 1)
        assert ("operate_binary_output", 2) not in handler.calls
        assert responses[0].to_bytes() == _expected_echo(request, [[_UNDEFINED, _UNDEFINED]])
        assert outstation._state.selection_of(MASTER_A) is None


class TestAnalogOutputDirectOperateRaises:
    """A raising g41 handler never reaches the tracking store (no SUCCESS, nothing to track)."""

    def test_raise_leaves_the_stored_value_unchanged(self) -> None:
        db = Database()
        db.add_analog_output(5, value=1.0)
        handler = _CallTrackingHandler(raise_on={"direct_operate_analog_output": {5}})
        outstation = _outstation(handler, database=db)

        request = _request(FunctionCode.DIRECT_OPERATE, _ao_block((5, 42)), seq=1)
        responses = outstation.process_request(request.to_bytes())

        point = db.get_analog_output(5)
        assert point is not None
        assert point.value == 1.0
        assert responses[0].to_bytes() == _expected_echo(request, [[_UNDEFINED]])


class _RaisingUpdateDatabase(Database):
    """update_analog_output always raises, standing for a broken tracking store."""

    def update_analog_output(
        self,
        index: int,
        value: float,
        quality: AnalogQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        msg = f"boom: update_analog_output {index}"
        raise RuntimeError(msg)


class TestTrackAoCommandWidenedCatch:
    """_track_ao_command catches any exception, not only ValueError (#46)."""

    def test_tracking_raise_after_success_keeps_status_success_and_logs_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingUpdateDatabase()
        db.add_analog_output(5, value=1.0)
        handler = _CallTrackingHandler()
        outstation = _outstation(handler, database=db)

        request = _request(FunctionCode.DIRECT_OPERATE, _ao_block((5, 42)), seq=1)
        with caplog.at_level(logging.ERROR, logger="dnp3.outstation.outstation"):
            responses = outstation.process_request(request.to_bytes())

        assert responses[0].to_bytes() == _expected_echo(request, [[int(CommandStatus.SUCCESS)]])
        records = [r for r in caplog.records if r.name == "dnp3.outstation.outstation"]
        assert len(records) == 1
        assert records[0].levelno == logging.ERROR
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is RuntimeError


class _BadReturnHandler(DefaultCommandHandler):
    """direct_operate_binary_output(1) returns something that is not a valid CommandResult."""

    def __init__(self, bad_return: object) -> None:
        super().__init__()
        self.bad_return = bad_return
        self.calls: list[int] = []

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.calls.append(index)
        if index == 1:
            return self.bad_return  # type: ignore[return-value]
        return CommandResult.success()


class TestInvalidHandlerReturnStops:
    """A handler returning something other than a valid CommandResult stops the request (row 10)."""

    @pytest.mark.parametrize(
        "bad_return",
        [
            pytest.param(None, id="none"),
            pytest.param(CommandResult(status=200), id="status-outside-commandstatus"),  # type: ignore[arg-type]
        ],
    )
    def test_bad_return_gives_undefined_and_stops_the_second_point(self, bad_return: object) -> None:
        handler = _BadReturnHandler(bad_return)
        outstation = _outstation(handler)

        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(1, 2), seq=1)
        responses = outstation.process_request(request.to_bytes())

        assert handler.calls == [1]
        assert responses[0].to_bytes() == _expected_echo(request, [[_UNDEFINED, _UNDEFINED]])


class TestNoAckStopsAfterRaise:
    """DIRECT_OPERATE_NO_ACK: silent either way, but a raise still stops the second point."""

    def test_raise_on_first_point_answers_nothing_and_skips_the_second(self, caplog: pytest.LogCaptureFixture) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {1}})
        outstation = _outstation(handler)
        request = _request(FunctionCode.DIRECT_OPERATE_NO_ACK, _crob_block(1, 2), seq=1)

        with caplog.at_level(logging.ERROR, logger="dnp3.outstation.outstation"):
            responses = outstation.process_request(request.to_bytes())

        assert responses == []
        assert handler.calls == [("direct_operate_binary_output", 1)]
        records = [r for r in caplog.records if r.name == "dnp3.outstation.outstation"]
        assert len(records) == 1


class TestKeyboardInterruptPropagates:
    """A KeyboardInterrupt from a control handler is not the exception this fix guards."""

    def test_keyboard_interrupt_still_propagates(self) -> None:
        handler = _CallTrackingHandler(raise_on={"direct_operate_binary_output": {1}}, exc=KeyboardInterrupt)
        outstation = _outstation(handler)
        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(1), seq=1)

        with pytest.raises(KeyboardInterrupt):
            outstation.process_request(request.to_bytes())
