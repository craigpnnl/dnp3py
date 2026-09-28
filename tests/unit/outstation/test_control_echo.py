"""A control response echoes each object of the request with that object's own status.

Request octets are built from IEEE 1815-2012 Annex A rather than this library's encoders. The
response echoes the request's object headers and objects with only each status octet set
(4.4.4.3 Rules 7 and 8), and a status belongs to one object by its position in the request, so
two objects naming one point never share a status.
"""

from __future__ import annotations

import struct

import pytest

from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.parser import parse_request
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.outstation import Outstation
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import PeerId

MASTER = PeerId(source=3, connection=1)

SUCCESS = CommandStatus.SUCCESS
NO_SELECT = CommandStatus.NO_SELECT
FORMAT_ERROR = CommandStatus.FORMAT_ERROR
REFUSED = CommandStatus.NOT_AUTHORIZED
LOCAL = CommandStatus.LOCAL

_IIN1_RESTART = 0x80
_IIN2_PARAMETER_ERROR = 0x04

# Octets per object after the 1-octet index prefix, status octet last (A.8.1, A.20.1 to A.20.3).
_OBJECT_OCTETS = {(12, 1): 11, (41, 1): 5, (41, 2): 3, (41, 3): 5}


def _crob(index: int, code: int = 0x03, on_time: int = 0) -> tuple[int, int, bytes]:
    """One g12v1 object: count 1, the given on-time, off-time 0, status 0."""
    return 12, 1, bytes([index, code, 1]) + on_time.to_bytes(4, "little") + bytes(4) + b"\x00"


def _g41v1(index: int, value: int) -> tuple[int, int, bytes]:
    return 41, 1, bytes([index]) + value.to_bytes(4, "little", signed=True) + b"\x00"


def _g41v2(index: int, value: int) -> tuple[int, int, bytes]:
    return 41, 2, bytes([index]) + value.to_bytes(2, "little", signed=True) + b"\x00"


def _g41v3(index: int, value: float) -> tuple[int, int, bytes]:
    return 41, 3, bytes([index]) + struct.pack("<f", value) + b"\x00"


Block = list[tuple[int, int, bytes]]


def _objects(*blocks: Block) -> tuple[bytes, list[int]]:
    """Each block as qualifier 0x17 octets, and the offset of every status octet in wire order."""
    octets = bytearray()
    status_offsets: list[int] = []
    for block in blocks:
        group, variation, _ = block[0]
        octets += bytes([group, variation, 0x17, len(block)])
        for _, _, body in block:
            octets += body
            status_offsets.append(len(octets) - 1)
    return bytes(octets), status_offsets


class _ScriptedHandler(DefaultCommandHandler):
    """Records every call with its arguments; answers from ``script`` in call order, then SUCCESS."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[object, ...]] = []
        self.script: list[CommandStatus] = []

    def _answer(self, *call: object) -> CommandResult:
        self.calls.append(call)
        return CommandResult(status=self.script.pop(0) if self.script else SUCCESS)

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._answer("bo_select", index, int(code), count, on_time, off_time)

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        return self._answer("bo_operate", index, int(code), count, on_time, off_time, select_sequence)

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._answer("bo_direct", index, int(code), count, on_time, off_time)

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        return self._answer("ao_select", index, value)

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        return self._answer("ao_operate", index, value, select_sequence)

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        return self._answer("ao_direct", index, value)


def _outstation() -> tuple[Outstation, _ScriptedHandler]:
    handler = _ScriptedHandler()
    return Outstation(config=OutstationConfig(time_sync_required=False), handler=handler), handler


def _request(function: FunctionCode, objects: bytes, seq: int) -> bytes:
    return bytes([0xC0 | seq, function.value]) + objects


def _send(outstation: Outstation, function: FunctionCode, objects: bytes, seq: int) -> bytes:
    responses: list[ResponseFragment] = outstation.process_request(_request(function, objects, seq), peer=MASTER)
    assert len(responses) == 1
    return responses[0].to_bytes()


def _echo(objects: bytes, status_offsets: list[int], statuses: list[CommandStatus], seq: int, iin2: int = 0) -> bytes:
    """The request's objects with only the status octets set, after a RESPONSE header."""
    assert len(status_offsets) == len(statuses)
    echoed = bytearray(objects)
    for offset, status in zip(status_offsets, statuses, strict=True):
        echoed[offset] = int(status)
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2]) + bytes(echoed)


def _calls(kind: str, *blocks: Block, select_sequence: int | None = None) -> list[tuple[object, ...]]:
    """The handler calls a request of these blocks makes, in wire order, when every point runs."""
    expected: list[tuple[object, ...]] = []
    for block in blocks:
        for group, variation, body in block:
            tail = () if select_sequence is None else (select_sequence,)
            if group == 12:
                on_time = int.from_bytes(body[3:7], "little")
                expected.append((f"bo_{kind}", body[0], body[1], body[2], on_time, 0, *tail))
            else:
                raw = body[1:-1]
                value = struct.unpack("<f", raw)[0] if variation == 3 else int.from_bytes(raw, "little", signed=True)
                expected.append((f"ao_{kind}", body[0], float(value), *tail))
    return expected


_MIXED = [
    pytest.param([_crob(1, on_time=100)], [_crob(2, code=0x41, on_time=250)], id="two-crob-blocks"),
    pytest.param([_g41v1(3, -7)], [_g41v3(4, 2.5)], id="g41v1-and-g41v3-blocks"),
    pytest.param([_crob(1, on_time=100)], [_g41v1(4, 1000)], id="crob-and-g41-blocks"),
]


class TestTwoBlockRequests:
    """Each block reaches the handler, and each object is echoed with the status it got."""

    @pytest.mark.parametrize(("first", "second"), _MIXED)
    def test_request_parses_as_two_blocks(self, first: Block, second: Block) -> None:
        objects, _ = _objects(first, second)

        request = parse_request(_request(FunctionCode.SELECT, objects, seq=1))

        assert request.objects == (
            ObjectBlock(
                ObjectHeader(group=first[0][0], variation=first[0][1], qualifier=0x17), bytes([1]) + first[0][2]
            ),
            ObjectBlock(
                ObjectHeader(group=second[0][0], variation=second[0][1], qualifier=0x17), bytes([1]) + second[0][2]
            ),
        )

    @pytest.mark.parametrize(("first", "second"), _MIXED)
    def test_select(self, first: Block, second: Block) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(first, second)
        handler.script = [SUCCESS, LOCAL]

        response = _send(outstation, FunctionCode.SELECT, objects, seq=1)

        assert handler.calls == _calls("select", first, second)
        assert response == _echo(objects, offsets, [SUCCESS, LOCAL], seq=1)

    @pytest.mark.parametrize(("first", "second"), _MIXED)
    def test_operate(self, first: Block, second: Block) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(first, second)
        assert _send(outstation, FunctionCode.SELECT, objects, seq=1) == _echo(objects, offsets, [SUCCESS] * 2, seq=1)
        handler.calls.clear()
        handler.script = [LOCAL, SUCCESS]

        response = _send(outstation, FunctionCode.OPERATE, objects, seq=2)

        assert handler.calls == _calls("operate", first, second, select_sequence=1)
        assert response == _echo(objects, offsets, [LOCAL, SUCCESS], seq=2)

    @pytest.mark.parametrize(("first", "second"), _MIXED)
    def test_direct_operate(self, first: Block, second: Block) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(first, second)
        handler.script = [SUCCESS, LOCAL]

        response = _send(outstation, FunctionCode.DIRECT_OPERATE, objects, seq=3)

        assert handler.calls == _calls("direct", first, second)
        assert response == _echo(objects, offsets, [SUCCESS, LOCAL], seq=3)


_DUPLICATES = [
    pytest.param(([_crob(5), _crob(5)],), "bo", id="crob-one-block"),
    pytest.param(([_crob(5)], [_crob(5)]), "bo", id="crob-two-blocks"),
    pytest.param(([_g41v2(5, 100), _g41v2(5, 100)],), "ao", id="g41-one-block"),
    pytest.param(([_g41v2(5, 100)], [_g41v2(5, 100)]), "ao", id="g41-two-blocks"),
]


class TestDuplicateIndex:
    """Two objects naming one point are answered separately, by position."""

    @pytest.mark.parametrize(("blocks", "kind"), _DUPLICATES)
    def test_operate_drives_once_and_answers_no_select_for_the_second(
        self, blocks: tuple[Block, ...], kind: str
    ) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(*blocks)
        assert _send(outstation, FunctionCode.SELECT, objects, seq=1) == _echo(objects, offsets, [SUCCESS] * 2, seq=1)
        handler.calls.clear()

        response = _send(outstation, FunctionCode.OPERATE, objects, seq=2)

        assert [call[:2] for call in handler.calls] == [(f"{kind}_operate", 5)]
        assert response == _echo(objects, offsets, [SUCCESS, NO_SELECT], seq=2)

    @pytest.mark.parametrize(("blocks", "kind"), _DUPLICATES)
    def test_direct_operate_answers_each_call_with_its_own_status(self, blocks: tuple[Block, ...], kind: str) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(*blocks)
        handler.script = [LOCAL, SUCCESS]

        response = _send(outstation, FunctionCode.DIRECT_OPERATE, objects, seq=4)

        assert [call[:2] for call in handler.calls] == [(f"{kind}_direct", 5)] * 2
        assert response == _echo(objects, offsets, [LOCAL, SUCCESS], seq=4)


_SHARED_INDEX = [
    pytest.param(([_crob(5)], [_g41v2(5, 100)]), id="crob-then-g41"),
    pytest.param(([_crob(5), _crob(5)],), id="crob-twice"),
]


class TestPartlyRefusedSelectOfOneIndex:
    """A refused object is echoed with its refusal even when an accepted object names the same index."""

    @pytest.mark.parametrize("blocks", _SHARED_INDEX)
    def test_select_echoes_the_refusal_and_arms_nothing(self, blocks: tuple[Block, ...]) -> None:
        outstation, handler = _outstation()
        objects, offsets = _objects(*blocks)
        handler.script = [REFUSED, SUCCESS]

        response = _send(outstation, FunctionCode.SELECT, objects, seq=1)

        assert response == _echo(objects, offsets, [REFUSED, SUCCESS], seq=1)
        selection = outstation._state.selection_of(MASTER)
        assert selection is not None
        assert selection.points == {}
        handler.calls.clear()
        assert _send(outstation, FunctionCode.OPERATE, objects, seq=2) == _echo(
            objects, offsets, [NO_SELECT, NO_SELECT], seq=2
        )
        assert handler.calls == []


class TestEchoWithoutAMatchingResult:
    """An object with no result of its own is echoed FORMAT_ERROR with IIN2.2, never another object's status."""

    @staticmethod
    def _request() -> tuple[Outstation, bytes, list[int]]:
        outstation, _ = _outstation()
        objects, offsets = _objects([_crob(1), _crob(2)], [_g41v2(3, 100)])
        return outstation, objects, offsets

    def _response(self, block_results: list[list[tuple[int, CommandStatus]]]) -> tuple[bytes, bytes, list[int]]:
        outstation, objects, offsets = self._request()
        request = parse_request(_request(FunctionCode.DIRECT_OPERATE, objects, seq=6))
        response = outstation._build_control_response(request, block_results)
        return response.to_bytes(), objects, offsets

    def test_aligned_results_echo_without_iin(self) -> None:
        response, objects, offsets = self._response([[(1, SUCCESS), (2, LOCAL)], [(3, REFUSED)]])

        assert response == _echo(objects, offsets, [SUCCESS, LOCAL, REFUSED], seq=6)

    @pytest.mark.parametrize(
        ("block_results", "statuses"),
        [
            pytest.param([[(1, SUCCESS)], [(3, REFUSED)]], [SUCCESS, FORMAT_ERROR, REFUSED], id="missing-entry"),
            pytest.param([[(1, SUCCESS), (2, LOCAL)]], [SUCCESS, LOCAL, FORMAT_ERROR], id="missing-block"),
            pytest.param([[(2, LOCAL), (1, SUCCESS)], [(3, REFUSED)]], [FORMAT_ERROR] * 2 + [REFUSED], id="swapped"),
            pytest.param(
                [[(1, SUCCESS), (2, LOCAL), (2, LOCAL)], [(3, REFUSED)]], [SUCCESS, LOCAL, REFUSED], id="extra-entry"
            ),
            pytest.param(
                [[(1, SUCCESS), (2, LOCAL)], [(3, REFUSED)], [(4, SUCCESS)]],
                [SUCCESS, LOCAL, REFUSED],
                id="extra-block",
            ),
        ],
    )
    def test_misaligned_results_echo_format_error_and_parameter_error(
        self, block_results: list[list[tuple[int, CommandStatus]]], statuses: list[CommandStatus]
    ) -> None:
        response, objects, offsets = self._response(block_results)

        assert response == _echo(objects, offsets, statuses, seq=6, iin2=_IIN2_PARAMETER_ERROR)
