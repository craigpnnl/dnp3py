"""OutstationConfig.max_controls_per_request is enforced across a request's control objects.

Objects beyond the limit are echoed with status TOO_MANY_OBJS (8, Table 11-7)
and never reach the handler.
"""

from __future__ import annotations

from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation

_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")  # LATCH_ON, count 1, on/off 0, status 0.
_CROB_RECORD_SIZE = 12  # 1-byte index + 11-byte body.
_AO_RECORD_SIZE = 4  # g41v2: 1-byte index + 2-byte value + status.


class _Handler(DefaultCommandHandler):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, int]] = []

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.calls.append(("select", index))
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.calls.append(("operate", index))
        return CommandResult.success()

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.calls.append(("direct", index))
        return CommandResult.success()

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        self.calls.append(("direct_ao", index))
        return CommandResult.success()


def _outstation(handler: _Handler, limit: int) -> Outstation:
    config = OutstationConfig(time_sync_required=False, max_controls_per_request=limit)
    return Outstation(config=config, handler=handler)


def _crob_block(*indices: int) -> ObjectBlock:
    data = bytes([len(indices)])
    for index in indices:
        data += bytes([index]) + _CROB_BODY
    return ObjectBlock(header=ObjectHeader(group=12, variation=1, qualifier=0x17), data=data)


def _ao_block(*indices: int) -> ObjectBlock:
    data = bytes([len(indices)])
    for index in indices:
        data += bytes([index]) + (5).to_bytes(2, "little", signed=True) + bytes([0])
    return ObjectBlock(header=ObjectHeader(group=41, variation=2, qualifier=0x17), data=data)


def _request(function: FunctionCode, *objects: ObjectBlock, seq: int = 0) -> bytes:
    return RequestFragment(header=RequestHeader.build(function=function, seq=seq), objects=objects).to_bytes()


def _statuses(response: ResponseFragment) -> list[CommandStatus]:
    out: list[CommandStatus] = []
    for block in response.objects:
        size = _CROB_RECORD_SIZE if block.header.group == 12 else _AO_RECORD_SIZE
        count = block.data[0]
        out.extend(CommandStatus(block.data[1 + position * size + size - 1]) for position in range(count))
    return out


class TestMaxControlsPerRequest:
    def test_direct_operate_beyond_limit_is_too_many_objs(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=2)
        responses = outstation.process_request(_request(FunctionCode.DIRECT_OPERATE, _crob_block(0, 1, 2)))
        assert _statuses(responses[0]) == [CommandStatus.SUCCESS, CommandStatus.SUCCESS, CommandStatus.TOO_MANY_OBJS]
        assert handler.calls == [("direct", 0), ("direct", 1)]

    def test_limit_counts_across_blocks(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=2)
        request = _request(FunctionCode.DIRECT_OPERATE, _crob_block(0), _ao_block(0, 1))
        responses = outstation.process_request(request)
        assert _statuses(responses[0]) == [CommandStatus.SUCCESS, CommandStatus.SUCCESS, CommandStatus.TOO_MANY_OBJS]
        assert handler.calls == [("direct", 0), ("direct_ao", 0)]

    def test_within_limit_all_carried_out(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=3)
        responses = outstation.process_request(_request(FunctionCode.DIRECT_OPERATE, _crob_block(0, 1, 2)))
        assert _statuses(responses[0]) == [CommandStatus.SUCCESS] * 3

    def test_direct_operate_no_ack_beyond_limit_not_carried_out(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=1)
        outstation.process_request(_request(FunctionCode.DIRECT_OPERATE_NO_ACK, _crob_block(0, 1)))
        assert handler.calls == [("direct", 0)]

    def test_select_beyond_limit_cancels_selection(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=1)
        select = outstation.process_request(_request(FunctionCode.SELECT, _crob_block(0, 1), seq=1))
        assert _statuses(select[0]) == [CommandStatus.SUCCESS, CommandStatus.TOO_MANY_OBJS]
        operate = outstation.process_request(_request(FunctionCode.OPERATE, _crob_block(0), seq=2))
        assert _statuses(operate[0]) == [CommandStatus.NO_SELECT]
        assert ("operate", 0) not in handler.calls

    def test_select_and_operate_within_limit(self) -> None:
        handler = _Handler()
        outstation = _outstation(handler, limit=2)
        select = outstation.process_request(_request(FunctionCode.SELECT, _crob_block(0, 1), seq=1))
        operate = outstation.process_request(_request(FunctionCode.OPERATE, _crob_block(0, 1), seq=2))
        assert _statuses(select[0]) == [CommandStatus.SUCCESS, CommandStatus.SUCCESS]
        assert _statuses(operate[0]) == [CommandStatus.SUCCESS, CommandStatus.SUCCESS]
        assert [call for call in handler.calls if call[0] == "operate"] == [("operate", 0), ("operate", 1)]
