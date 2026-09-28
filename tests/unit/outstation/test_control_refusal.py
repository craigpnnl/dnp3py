"""A control request runs nothing it should not when any part of it is unusable.

Request octets are built from IEEE 1815-2012 Annex A rather than this library's encoders.
Every control block is decoded before any point runs, so a block the control path cannot
use refuses the whole request with no objects (4.4.4.3 Rule 6 item 1): IIN2.1 for an
object that is not a control (Table 4-14), IIN2.2 for a malformed block. A SELECT answered
with a non-zero status in any object arms nothing (4.4.4.3 Rule 3).
"""

from __future__ import annotations

import time

import pytest

from dnp3.application.builder import build_direct_operate_request, build_operate_request, build_select_request
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.outstation import Outstation
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)

SUCCESS = CommandStatus.SUCCESS
NO_SELECT = CommandStatus.NO_SELECT
BLOCKED = CommandStatus.BLOCKED_OTHER_MASTER
REFUSED = CommandStatus.NOT_AUTHORIZED
FORMAT_ERROR = CommandStatus.FORMAT_ERROR

_IIN1_RESTART = 0x80
_IIN2_OBJECT_UNKNOWN = 0x02
_IIN2_PARAMETER_ERROR = 0x04

# g12v1 (A.8.1): control code LATCH_ON, count 1, on-time, off-time, status.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")
# g41v2 (A.20.2): INT16 value 100, status.
_G41V2_BODY = bytes.fromhex("6400 00")


def _crob(*indexes: int) -> bytes:
    """g12v1, qualifier 0x17, one LATCH_ON object per index."""
    return bytes([0x0C, 0x01, 0x17, len(indexes)]) + b"".join(bytes([index]) + _CROB_BODY for index in indexes)


def _g41v2(*indexes: int) -> bytes:
    """g41v2, qualifier 0x17, value 100 at each index."""
    return bytes([0x29, 0x02, 0x17, len(indexes)]) + b"".join(bytes([index]) + _G41V2_BODY for index in indexes)


# Qualifier 0x07 (count, no index prefix) frames, but a control object must name its point.
_CROB_NO_INDEX = bytes([0x0C, 0x01, 0x07, 0x01]) + _CROB_BODY
_G41V2_NO_INDEX = bytes([0x29, 0x02, 0x07, 0x01]) + _G41V2_BODY
# g40v1 (A.19.1: flags, INT32) at index 0: a status object, not a control.
_G40V1 = bytes.fromhex("28 01 00 00 00 01 E8030000")
# g12v2 has no width this outstation knows, so framing refuses it before the control path sees it.
_G12V2 = bytes([0x0C, 0x02, 0x17, 0x01, 0x02]) + _CROB_BODY

_UNDECODABLE = [
    pytest.param(_crob(1) + _CROB_NO_INDEX, _IIN2_PARAMETER_ERROR, id="crob-without-index"),
    pytest.param(_crob(1) + _G41V2_NO_INDEX, _IIN2_PARAMETER_ERROR, id="analog-output-without-index"),
    pytest.param(_crob(1) + _G40V1, _IIN2_OBJECT_UNKNOWN, id="analog-output-status"),
    pytest.param(_G40V1 + _crob(1), _IIN2_OBJECT_UNKNOWN, id="analog-output-status-first"),
    pytest.param(_crob(1) + _G12V2, _IIN2_OBJECT_UNKNOWN, id="pattern-control-block-unframed"),
    # Two failing blocks: the IIN bit is the first one's (4.4.4.3 Rule 7).
    pytest.param(_G40V1 + _CROB_NO_INDEX, _IIN2_OBJECT_UNKNOWN, id="unknown-then-malformed"),
    pytest.param(_CROB_NO_INDEX + _G40V1, _IIN2_PARAMETER_ERROR, id="malformed-then-unknown"),
]

_G41V2_HEADER = ObjectHeader(group=41, variation=2, qualifier=0x17)
# Blocks framing would refuse on the wire, each naming index 5 of g41v2 or index 1 of g12v1 first.
_HAND_BUILT = [
    # Declares 2 objects and holds 1.
    pytest.param(
        ObjectBlock(_G41V2_HEADER, bytes([2]) + _g41v2(5)[4:]), _IIN2_PARAMETER_ERROR, id="analog-output-short"
    ),
    # One octet after the declared object.
    pytest.param(
        ObjectBlock(_G41V2_HEADER, _g41v2(5)[3:] + bytes([6])), _IIN2_PARAMETER_ERROR, id="analog-output-long"
    ),
    pytest.param(
        ObjectBlock(ObjectHeader(group=12, variation=1, qualifier=0x17), _crob(1, 2)[3:-12]),
        _IIN2_PARAMETER_ERROR,
        id="crob-short",
    ),
    # Not a variation g41 defines.
    pytest.param(
        ObjectBlock(ObjectHeader(group=41, variation=5, qualifier=0x17), bytes([1, 5, 0, 0, 0])),
        _IIN2_OBJECT_UNKNOWN,
        id="analog-output-unknown-variation",
    ),
    # Sized exactly as a g12v1 object, but only g12v1 is a control.
    pytest.param(
        ObjectBlock(ObjectHeader(group=12, variation=2, qualifier=0x17), bytes([1, 1]) + _CROB_BODY),
        _IIN2_OBJECT_UNKNOWN,
        id="pattern-control-block",
    ),
]
_CONTROL_FUNCTIONS = [
    FunctionCode.SELECT,
    FunctionCode.OPERATE,
    FunctionCode.DIRECT_OPERATE,
    FunctionCode.DIRECT_OPERATE_NO_ACK,
]


class _RecordingHandler(DefaultCommandHandler):
    """Records every command and answers with a per-(kind, index) status, SUCCESS by default."""

    def __init__(self) -> None:
        super().__init__()
        self.statuses: dict[tuple[str, int], CommandStatus] = {}
        self.calls: list[tuple[str, int]] = []

    def _record(self, kind: str, index: int) -> CommandResult:
        self.calls.append((kind, index))
        return CommandResult(status=self.statuses.get((kind, index), SUCCESS))

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._record("bo_select", index)

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        return self._record("bo_operate", index)

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._record("bo_direct", index)

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        return self._record("ao_select", index)

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        return self._record("ao_operate", index)

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        return self._record("ao_direct", index)


def _outstation(select_timeout: float = 10.0) -> tuple[Outstation, _RecordingHandler]:
    handler = _RecordingHandler()
    config = OutstationConfig(time_sync_required=False, select_timeout=select_timeout)
    return Outstation(config=config, handler=handler), handler


def _send(
    outstation: Outstation, function: FunctionCode, objects: bytes, seq: int, peer: PeerId = MASTER_A
) -> list[ResponseFragment]:
    return outstation.process_request(bytes([0xC0 | seq, function.value]) + objects, peer=peer)


def _only(responses: list[ResponseFragment]) -> bytes:
    assert len(responses) == 1
    return responses[0].to_bytes()


def _null_response(seq: int, iin2: int) -> bytes:
    """A null RESPONSE (FIR, FIN) from a restarted outstation, with IIN2 set as given."""
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2])


def _echo(objects: bytes, seq: int, statuses: dict[int, CommandStatus], iin2: int = 0x00) -> bytes:
    """A RESPONSE echoing ``objects``, with the status octet at each given offset replaced."""
    echoed = bytearray(objects)
    for offset, status in statuses.items():
        echoed[offset] = int(status)
    return _null_response(seq, iin2) + bytes(echoed)


# Offsets of each object's status octet in _crob(a, b) and in _crob(a) + _crob(b).
_ONE_BLOCK_STATUS = (4 + 11, 4 + 12 + 11)
_TWO_BLOCK_STATUS = (4 + 11, 16 + 4 + 11)
# SELECTs of index 1 then index 2, the handler kind each calls, and each status octet offset.
_PARTLY_REFUSED = [
    pytest.param(_crob(1, 2), "bo_select", _ONE_BLOCK_STATUS, id="one-crob-block"),
    pytest.param(_crob(1) + _crob(2), "bo_select", _TWO_BLOCK_STATUS, id="two-crob-blocks"),
    pytest.param(_g41v2(1, 2), "ao_select", (4 + 1 + 2, 4 + 4 + 1 + 2), id="one-analog-output-block"),
]


class TestUndecodableBlockRunsNothing:
    """A block the control path cannot use refuses the request before any point runs."""

    @pytest.mark.parametrize(("objects", "iin2"), _UNDECODABLE)
    @pytest.mark.parametrize("function", _CONTROL_FUNCTIONS, ids=[function.name for function in _CONTROL_FUNCTIONS])
    def test_request_calls_no_handler_and_answers_a_null_response(
        self, function: FunctionCode, objects: bytes, iin2: int
    ) -> None:
        outstation, handler = _outstation()

        responses = _send(outstation, function, objects, seq=7)

        if function == FunctionCode.DIRECT_OPERATE_NO_ACK:
            assert responses == []
        else:
            assert _only(responses) == _null_response(7, iin2)
        assert handler.calls == []
        assert outstation._state.selection_of(MASTER_A) is None

    @pytest.mark.parametrize(("objects", "iin2"), _UNDECODABLE)
    def test_operate_after_the_refused_select_actuates_nothing(self, objects: bytes, iin2: int) -> None:
        outstation, handler = _outstation()
        _send(outstation, FunctionCode.SELECT, objects, seq=2)

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=3))

        assert response == _null_response(3, iin2)
        assert handler.calls == []

    def test_refused_select_holds_no_point_against_another_master(self) -> None:
        outstation, handler = _outstation()
        _send(outstation, FunctionCode.SELECT, _crob(1) + _G40V1, seq=2)

        response = _only(_send(outstation, FunctionCode.SELECT, _crob(1), seq=5, peer=MASTER_B))

        assert response == _echo(_crob(1), 5, {})
        assert handler.calls == [("bo_select", 1)]


class TestHandBuiltBlockRunsNothing:
    """A block that reaches the control handlers without framing is checked the same way.

    Framing refuses these on the wire, so each request is built as a fragment and handed to
    the handler directly.
    """

    @staticmethod
    def _armed(outstation: Outstation) -> None:
        """Select index 5 of g41v2 and index 1 of g12v1, the points each malformed block names first."""
        _only(_send(outstation, FunctionCode.SELECT, _g41v2(5) + _crob(1), seq=0))

    @pytest.mark.parametrize(("block", "iin2"), _HAND_BUILT)
    def test_select_arms_nothing(self, block: ObjectBlock, iin2: int) -> None:
        outstation, handler = _outstation()

        response = outstation._handle_select(build_select_request(objects=(block,), seq=4), peer=MASTER_A)

        assert response.to_bytes() == _null_response(4, iin2)
        assert handler.calls == []
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is None
        assert outstation._state.get_select(1, peer=MASTER_A) is None

    @pytest.mark.parametrize(("block", "iin2"), _HAND_BUILT)
    def test_operate_actuates_nothing(self, block: ObjectBlock, iin2: int) -> None:
        outstation, handler = _outstation()
        self._armed(outstation)
        handler.calls.clear()

        response = outstation._handle_operate(build_operate_request(objects=(block,), seq=1), peer=MASTER_A)

        assert response.to_bytes() == _null_response(1, iin2)
        assert handler.calls == []

    @pytest.mark.parametrize(("block", "iin2"), _HAND_BUILT)
    def test_direct_operate_actuates_nothing(self, block: ObjectBlock, iin2: int) -> None:
        outstation, handler = _outstation()

        response = outstation._handle_direct_operate(build_direct_operate_request(objects=(block,), seq=2))

        assert response.to_bytes() == _null_response(2, iin2)
        assert handler.calls == []


class TestSelectWithAnyRefusalArmsNothing:
    """A non-zero status in any object of a SELECT response cancels the entire selection."""

    @pytest.mark.parametrize(("objects", "kind", "status_offsets"), _PARTLY_REFUSED)
    def test_echo_carries_each_status_and_no_point_stays_armed(
        self, objects: bytes, kind: str, status_offsets: tuple[int, int]
    ) -> None:
        outstation, handler = _outstation()
        handler.statuses[(kind, 2)] = REFUSED

        response = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))

        first, second = status_offsets
        assert response == _echo(objects, 2, {first: SUCCESS, second: REFUSED})
        assert handler.calls == [(kind, 1), (kind, 2)]
        selection = outstation._state.selection_of(MASTER_A)
        assert selection is not None
        assert selection.points == {}

    @pytest.mark.parametrize(("objects", "kind", "status_offsets"), _PARTLY_REFUSED)
    def test_identical_operate_is_no_select_for_every_object(
        self, objects: bytes, kind: str, status_offsets: tuple[int, int]
    ) -> None:
        outstation, handler = _outstation()
        handler.statuses[(kind, 2)] = REFUSED
        _send(outstation, FunctionCode.SELECT, objects, seq=2)
        handler.calls.clear()

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=3))

        first, second = status_offsets
        assert response == _echo(objects, 3, {first: NO_SELECT, second: NO_SELECT})
        assert handler.calls == []

    def test_another_master_can_select_the_point_that_succeeded(self) -> None:
        outstation, handler = _outstation()
        handler.statuses[("bo_select", 2)] = REFUSED
        _send(outstation, FunctionCode.SELECT, _crob(1, 2), seq=2)

        response = _only(_send(outstation, FunctionCode.SELECT, _crob(1), seq=9, peer=MASTER_B))

        assert response == _echo(_crob(1), 9, {})

    def test_a_point_blocked_by_another_master_cancels_the_rest(self) -> None:
        outstation, handler = _outstation()
        _send(outstation, FunctionCode.SELECT, _crob(2), seq=0, peer=MASTER_B)
        objects = _crob(1, 2)

        response = _only(_send(outstation, FunctionCode.SELECT, objects, seq=4))
        operate = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=5))

        first, second = _ONE_BLOCK_STATUS
        assert response == _echo(objects, 4, {first: SUCCESS, second: BLOCKED})
        assert operate == _echo(objects, 5, {first: NO_SELECT, second: NO_SELECT})
        assert ("bo_operate", 1) not in handler.calls
        assert outstation._state.get_select(2, peer=MASTER_B) is not None

    def test_select_whose_every_point_succeeds_still_operates(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1, 2)
        _send(outstation, FunctionCode.SELECT, objects, seq=2)

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=3))

        assert response == _echo(objects, 3, {})
        assert handler.calls[-2:] == [("bo_operate", 1), ("bo_operate", 2)]

    def test_a_format_error_in_one_object_cancels_the_rest(self) -> None:
        outstation, handler = _outstation()
        first, second = _ONE_BLOCK_STATUS
        objects = bytearray(_crob(1, 2))
        # Index 2's control code: Op Type 5 is not defined.
        objects[second - 10] = 0x05
        request = bytes(objects)

        select = _only(_send(outstation, FunctionCode.SELECT, request, seq=2))
        operate = _only(_send(outstation, FunctionCode.OPERATE, request, seq=3))

        assert select == _echo(request, 2, {first: SUCCESS, second: FORMAT_ERROR}, _IIN2_PARAMETER_ERROR)
        assert operate == _echo(request, 3, {first: NO_SELECT, second: FORMAT_ERROR}, _IIN2_PARAMETER_ERROR)
        assert handler.calls == [("bo_select", 1)]


class TestPartlyRefusedSelectRetry:
    """A partly refused SELECT stays the request a retry is judged against (IEEE 1815-2012 Table 4-9).

    The record keeps its response and no points, so a retry repeats that response and runs nothing.
    """

    @staticmethod
    def _select_then_accept_every_point(outstation: Outstation, handler: _RecordingHandler, objects: bytes) -> bytes:
        """SELECT with index 2 refused, then let the handler accept every point."""
        for kind in ("bo_select", "ao_select"):
            handler.statuses[(kind, 2)] = REFUSED
        first = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))
        handler.statuses.clear()
        handler.calls.clear()
        return first

    @pytest.mark.parametrize(("objects", "kind", "status_offsets"), _PARTLY_REFUSED)
    def test_retry_repeats_the_first_response_without_the_handlers(
        self, objects: bytes, kind: str, status_offsets: tuple[int, int]
    ) -> None:
        outstation, handler = _outstation()
        first = self._select_then_accept_every_point(outstation, handler, objects)

        retry = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))

        assert retry == first
        assert handler.calls == []
        selection = outstation._state.selection_of(MASTER_A)
        assert selection is not None
        assert selection.points == {}

    @pytest.mark.parametrize(("objects", "kind", "status_offsets"), _PARTLY_REFUSED)
    def test_operate_after_the_retry_is_no_select_for_every_object(
        self, objects: bytes, kind: str, status_offsets: tuple[int, int]
    ) -> None:
        outstation, handler = _outstation()
        self._select_then_accept_every_point(outstation, handler, objects)
        _send(outstation, FunctionCode.SELECT, objects, seq=2)

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=3))

        first, second = status_offsets
        assert response == _echo(objects, 3, {first: NO_SELECT, second: NO_SELECT})
        assert handler.calls == []
        assert outstation._state.selection_of(MASTER_A) is None

    def test_direct_select_leaves_no_record(self) -> None:
        # With no request octets there is nothing a retry could be matched against.
        outstation, handler = _outstation()
        handler.statuses[("bo_select", 2)] = REFUSED
        block = ObjectBlock(ObjectHeader(group=12, variation=1, qualifier=0x17), _crob(1, 2)[3:])

        outstation._handle_select(build_select_request(objects=(block,), seq=2), peer=MASTER_A)

        assert handler.calls == [("bo_select", 1), ("bo_select", 2)]
        assert outstation._state.selection_of(MASTER_A) is None

    def test_record_expires_on_the_selection_timer(self) -> None:
        timeout = 0.2
        outstation, handler = _outstation(select_timeout=timeout)
        objects = _crob(1, 2)
        self._select_then_accept_every_point(outstation, handler, objects)

        time.sleep(timeout * 1.5)
        retry = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))

        assert retry == _echo(objects, 2, {})
        assert handler.calls == [("bo_select", 1), ("bo_select", 2)]
