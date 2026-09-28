"""SELECT and OPERATE of analog output blocks (group 41) in the outstation.

IEEE 1815-2012 Table 14-3 lists SELECT (3) and OPERATE (4) of g41 for a
Level 2 outstation. An analog output selection follows the same per-master
Table 4-9 rules as a CROB selection, and a selection of one group never
satisfies an OPERATE of the other at the same index.
"""

from __future__ import annotations

import struct
import time

import pytest

from dnp3.application.builder import build_direct_operate_request, build_operate_request, build_select_request
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.header import RESPONSE_HEADER_SIZE
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.core.flags import IIN
from dnp3.outstation import Outstation
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)

SUCCESS = CommandStatus.SUCCESS
NO_SELECT = CommandStatus.NO_SELECT
BLOCKED = CommandStatus.BLOCKED_OTHER_MASTER
NOT_SUPPORTED = CommandStatus.NOT_SUPPORTED
OUT_OF_RANGE = CommandStatus.OUT_OF_RANGE

# (variation, value format, value) for g41v1 to g41v4; each value survives its encoding exactly.
VARIATIONS = [
    pytest.param(1, "<i", -123456.0, id="g41v1-int32"),
    pytest.param(2, "<h", -300.0, id="g41v2-int16"),
    pytest.param(3, "<f", 12.5, id="g41v3-float32"),
    pytest.param(4, "<d", 0.1, id="g41v4-float64"),
]
QUALIFIERS = [pytest.param(0x17, id="q17"), pytest.param(0x28, id="q28")]


class _RecordingHandler(DefaultCommandHandler):
    """Records every output command and answers with a per-(kind, index) status, SUCCESS by default."""

    def __init__(self) -> None:
        super().__init__()
        self.statuses: dict[tuple[str, int], CommandStatus] = {}
        self.ao_selects: list[tuple[int, float]] = []
        self.ao_operates: list[tuple[int, float, int]] = []
        self.ao_direct: list[tuple[int, float]] = []
        self.bo_selects: list[int] = []
        self.bo_operates: list[int] = []

    def _result(self, kind: str, index: int) -> CommandResult:
        return CommandResult(status=self.statuses.get((kind, index), SUCCESS))

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        self.ao_selects.append((index, value))
        return self._result("ao_select", index)

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        self.ao_operates.append((index, value, select_sequence))
        return self._result("ao_operate", index)

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        self.ao_direct.append((index, value))
        return self._result("ao_direct", index)

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.bo_selects.append(index)
        return self._result("bo_select", index)

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.bo_operates.append(index)
        return self._result("bo_operate", index)


def _ao_block(
    variation: int, fmt: str, points: list[tuple[int, float]], qualifier: int = 0x17, status: int = 0
) -> ObjectBlock:
    """g41 block: count, then per object an index prefix, the value and a status octet."""
    width = 1 if qualifier == 0x17 else 2
    data = bytearray(len(points).to_bytes(width, "little"))
    for index, value in points:
        encoded = struct.pack(fmt, int(value) if fmt in {"<i", "<h"} else value)
        data += index.to_bytes(width, "little") + encoded + bytes([status])
    return ObjectBlock(header=ObjectHeader(group=41, variation=variation, qualifier=qualifier), data=bytes(data))


def _crob_block(index: int) -> ObjectBlock:
    """g12v1, qualifier 0x17, one LATCH_ON object at ``index``."""
    body = bytes([1, index, int(ControlCode.LATCH_ON), 1]) + (0).to_bytes(4, "little") * 2 + bytes([0])
    return ObjectBlock(header=ObjectHeader(group=12, variation=1, qualifier=0x17), data=body)


def _echo(block: ObjectBlock, statuses: list[CommandStatus]) -> bytes:
    """Wire bytes of ``block`` with each object's status octet replaced, in object order."""
    header = block.header
    width = 1 if header.qualifier == 0x17 else 2
    size = len(block.data[width:]) // len(statuses)
    data = bytearray(block.data)
    for position, status in enumerate(statuses):
        data[width + size * (position + 1) - 1] = int(status)
    return bytes([header.group, header.variation, header.qualifier]) + bytes(data)


def _objects_on_wire(response: ResponseFragment) -> bytes:
    """The octets a master receives after the response header."""
    return response.to_bytes()[RESPONSE_HEADER_SIZE:]


def _send(outstation: Outstation, request_bytes: bytes, peer: PeerId | None) -> ResponseFragment:
    responses = outstation.process_request(request_bytes, peer=peer)
    assert len(responses) == 1
    return responses[0]


def _select(outstation: Outstation, peer: PeerId | None, *blocks: ObjectBlock, seq: int = 0) -> ResponseFragment:
    return _send(outstation, build_select_request(objects=blocks, seq=seq).to_bytes(), peer)


def _operate(outstation: Outstation, peer: PeerId | None, *blocks: ObjectBlock, seq: int = 1) -> ResponseFragment:
    return _send(outstation, build_operate_request(objects=blocks, seq=seq).to_bytes(), peer)


def _outstation() -> tuple[Outstation, _RecordingHandler]:
    handler = _RecordingHandler()
    return Outstation(handler=handler), handler


class TestSelectAnalogOutput:
    """SELECT of g41 calls select_analog_output per point and echoes its status."""

    @pytest.mark.parametrize("qualifier", QUALIFIERS)
    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_select_echoes_handler_status_and_arms_the_point(
        self, variation: int, fmt: str, value: float, qualifier: int
    ) -> None:
        outstation, handler = _outstation()
        block = _ao_block(variation, fmt, [(5, value)], qualifier)

        response = _select(outstation, MASTER_A, block, seq=6)

        assert _objects_on_wire(response) == _echo(block, [SUCCESS])
        assert not response.header.iin & IIN.PARAMETER_ERROR
        assert handler.ao_selects == [(5, value)]
        assert handler.ao_operates == []
        stored = outstation._state.get_select(5, peer=MASTER_A, group=41)
        assert stored is not None
        assert (stored.index, stored.is_binary, stored.analog_value, stored.sequence) == (5, False, value, 6)
        assert outstation._state.get_select(5, peer=MASTER_A) is None

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_rejected_select_echoes_the_rejection_and_arms_nothing(
        self, variation: int, fmt: str, value: float
    ) -> None:
        outstation, handler = _outstation()
        handler.statuses[("ao_select", 5)] = OUT_OF_RANGE
        block = _ao_block(variation, fmt, [(5, value)])

        response = _select(outstation, MASTER_A, block)

        assert _objects_on_wire(response) == _echo(block, [OUT_OF_RANGE])
        assert handler.ao_selects == [(5, value)]
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is None
        assert outstation._state.selection_of(MASTER_A) is None

    def test_status_is_per_object(self) -> None:
        outstation, handler = _outstation()
        handler.statuses[("ao_select", 6)] = NOT_SUPPORTED
        block = _ao_block(3, "<f", [(5, 1.5), (6, 2.5)])

        response = _select(outstation, MASTER_A, block)

        assert _objects_on_wire(response) == _echo(block, [SUCCESS, NOT_SUPPORTED])
        assert handler.ao_selects == [(5, 1.5), (6, 2.5)]
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is not None
        assert outstation._state.get_select(6, peer=MASTER_A, group=41) is None

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_point_held_by_another_master_is_17_without_the_handler(
        self, variation: int, fmt: str, value: float
    ) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _ao_block(variation, fmt, [(5, value)]))
        block_b = _ao_block(variation, fmt, [(5, value)])

        response = _select(outstation, MASTER_B, block_b)

        assert int(BLOCKED) == 17
        assert _objects_on_wire(response) == _echo(block_b, [BLOCKED])
        assert handler.ao_selects == [(5, value)]
        assert outstation._state.get_select(5, peer=MASTER_B, group=41) is None
        held = outstation._state.get_select(5, peer=MASTER_A, group=41)
        assert held is not None
        assert held.analog_value == value

    def test_a_crob_selection_does_not_block_an_analog_select_at_the_same_index(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _crob_block(5))
        block_b = _ao_block(3, "<f", [(5, 2.5)])

        response = _select(outstation, MASTER_B, block_b)

        assert _objects_on_wire(response) == _echo(block_b, [SUCCESS])
        assert handler.ao_selects == [(5, 2.5)]

    def test_truncated_block_selects_the_whole_objects_and_flags_parameter_error(self) -> None:
        outstation, handler = _outstation()
        whole = _ao_block(3, "<f", [(5, 1.5)])
        block = ObjectBlock(header=whole.header, data=bytes([2]) + whole.data[1:] + bytes([6, 0]))

        response = _select(outstation, MASTER_A, block)

        assert response.header.iin & IIN.PARAMETER_ERROR
        assert handler.ao_selects == [(5, 1.5)]


class TestMalformedAnalogOutputBlock:
    """A g41 block that cannot be parsed reaches no handler and sets IIN.PARAMETER_ERROR."""

    @pytest.mark.parametrize(
        ("variation", "qualifier"), [(5, 0x17), (3, 0x07)], ids=["unknown-variation", "unknown-qualifier"]
    )
    @pytest.mark.parametrize("function", ["select", "operate"])
    def test_malformed_block_flags_parameter_error(self, function: str, variation: int, qualifier: int) -> None:
        outstation, handler = _outstation()
        block = ObjectBlock(
            header=ObjectHeader(group=41, variation=variation, qualifier=qualifier),
            data=bytes([1, 5, 0, 0, 0xC0, 0x3F, 0]),
        )
        send = _select if function == "select" else _operate

        response = send(outstation, MASTER_A, block)

        assert response.header.iin & IIN.PARAMETER_ERROR
        assert handler.ao_selects == []
        assert handler.ao_operates == []
        assert outstation._state.selection_of(MASTER_A) is None


class TestOperateAnalogOutput:
    """OPERATE of g41 reaches operate_analog_output only through this master's matching selection."""

    @pytest.mark.parametrize("qualifier", QUALIFIERS)
    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_select_then_operate_calls_the_handler_and_echoes_its_status(
        self, variation: int, fmt: str, value: float, qualifier: int
    ) -> None:
        outstation, handler = _outstation()
        handler.statuses[("ao_operate", 5)] = CommandStatus.HARDWARE_ERROR
        block = _ao_block(variation, fmt, [(5, value)], qualifier)
        _select(outstation, MASTER_A, block, seq=6)

        response = _operate(outstation, MASTER_A, block, seq=7)

        assert _objects_on_wire(response) == _echo(block, [CommandStatus.HARDWARE_ERROR])
        assert handler.ao_operates == [(5, value, 6)]
        assert handler.ao_direct == []
        assert outstation._state.selection_of(MASTER_A) is None

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_operate_with_another_value_is_no_select(self, variation: int, fmt: str, value: float) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _ao_block(variation, fmt, [(5, value)]))
        other = _ao_block(variation, fmt, [(5, value + 1.0)])

        response = _operate(outstation, MASTER_A, other)

        assert _objects_on_wire(response) == _echo(other, [NO_SELECT])
        assert handler.ao_operates == []
        assert outstation._state.selection_of(MASTER_A) is None

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_operate_of_another_index_is_no_select(self, variation: int, fmt: str, value: float) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _ao_block(variation, fmt, [(5, value)]))
        other = _ao_block(variation, fmt, [(6, value)])

        response = _operate(outstation, MASTER_A, other)

        assert _objects_on_wire(response) == _echo(other, [NO_SELECT])
        assert handler.ao_operates == []

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_operate_after_the_selection_expired_is_no_select(self, variation: int, fmt: str, value: float) -> None:
        outstation, handler = _outstation()
        block = _ao_block(variation, fmt, [(5, value)])
        _select(outstation, MASTER_A, block)
        held = outstation._state.get_select(5, peer=MASTER_A, group=41)
        assert held is not None
        held.timestamp = time.monotonic() - 2 * outstation.config.select_timeout

        response = _operate(outstation, MASTER_A, block)

        assert _objects_on_wire(response) == _echo(block, [NO_SELECT])
        assert handler.ao_operates == []

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_operate_from_another_master_is_no_select_and_the_holder_still_operates(
        self, variation: int, fmt: str, value: float
    ) -> None:
        outstation, handler = _outstation()
        block = _ao_block(variation, fmt, [(5, value)])
        _select(outstation, MASTER_A, block)

        response_b = _operate(outstation, MASTER_B, block)

        assert _objects_on_wire(response_b) == _echo(block, [NO_SELECT])
        assert handler.ao_operates == []

        response_a = _operate(outstation, MASTER_A, block)

        assert _objects_on_wire(response_a) == _echo(block, [SUCCESS])
        assert handler.ao_operates == [(5, value, 0)]

    def test_operate_without_any_selection_is_no_select(self) -> None:
        outstation, handler = _outstation()
        block = _ao_block(3, "<f", [(5, 1.5)])

        response = _operate(outstation, MASTER_A, block, seq=0)

        assert _objects_on_wire(response) == _echo(block, [NO_SELECT])
        assert handler.ao_operates == []

    def test_stored_value_must_match_the_operate_value(self) -> None:
        # The request octets match, so only the per-point value comparison can refuse this OPERATE.
        outstation, handler = _outstation()
        block = _ao_block(3, "<f", [(5, 1.5)])
        _select(outstation, MASTER_A, block)
        held = outstation._state.get_select(5, peer=MASTER_A, group=41)
        assert held is not None
        held.analog_value = 2.5

        response = _operate(outstation, MASTER_A, block)

        assert _objects_on_wire(response) == _echo(block, [NO_SELECT])
        assert handler.ao_operates == []

    def test_operate_of_a_rejected_point_is_no_select_and_its_neighbour_operates(self) -> None:
        outstation, handler = _outstation()
        handler.statuses[("ao_select", 6)] = OUT_OF_RANGE
        block = _ao_block(3, "<f", [(5, 1.5), (6, 2.5)])
        _select(outstation, MASTER_A, block)

        response = _operate(outstation, MASTER_A, block)

        assert _objects_on_wire(response) == _echo(block, [SUCCESS, NO_SELECT])
        assert handler.ao_operates == [(5, 1.5, 0)]


class TestGroupsDoNotSatisfyEachOther:
    """A CROB selection and an analog output selection at one index are separate points.

    The OPERATE is handed to the per-point stage directly: through
    process_request its octets would differ from the SELECT's, and the
    Table 4-9 comparison would refuse it before any point is looked up.
    """

    @staticmethod
    def _operate_points(outstation: Outstation, block: ObjectBlock) -> ResponseFragment:
        request = build_operate_request(objects=(block,), seq=1)
        return outstation._handle_operate(request, peer=MASTER_A)

    def test_crob_selection_does_not_satisfy_an_analog_operate(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _crob_block(5))
        assert outstation._state.get_select(5, peer=MASTER_A) is not None
        analog = _ao_block(3, "<f", [(5, 1.5)])

        response = self._operate_points(outstation, analog)

        assert _objects_on_wire(response) == _echo(analog, [NO_SELECT])
        assert handler.ao_operates == []
        assert outstation._state.get_select(5, peer=MASTER_A) is not None

    def test_analog_selection_does_not_satisfy_a_crob_operate(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _ao_block(3, "<f", [(5, 1.5)]))
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is not None
        crob = _crob_block(5)

        response = self._operate_points(outstation, crob)

        assert _objects_on_wire(response) == _echo(crob, [NO_SELECT])
        assert handler.bo_operates == []
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is not None

    def test_each_group_operates_its_own_selection_at_one_index(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, _crob_block(5))
        crob_selection = outstation._state.get_select(5, peer=MASTER_A)
        _select(outstation, MASTER_A, _ao_block(3, "<f", [(5, 1.5)]), seq=1)
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is not None
        # The second SELECT ended the first selection (Table 4-9); re-arm the CROB point beside it.
        assert crob_selection is not None
        outstation._state.add_select(crob_selection, peer=MASTER_A)
        analog = _ao_block(3, "<f", [(5, 1.5)])

        response = self._operate_points(outstation, analog)

        assert _objects_on_wire(response) == _echo(analog, [SUCCESS])
        assert handler.ao_operates == [(5, 1.5, 1)]
        kept = outstation._state.get_select(5, peer=MASTER_A)
        assert kept is not None
        assert (kept.is_binary, kept.control_code) == (True, ControlCode.LATCH_ON)
        assert outstation._state.get_select(5, peer=MASTER_A, group=41) is None


class TestDirectOperateUnchanged:
    """DIRECT_OPERATE of g41 needs no selection and arms nothing."""

    @pytest.mark.parametrize(("variation", "fmt", "value"), VARIATIONS)
    def test_direct_operate_calls_only_the_direct_handler(self, variation: int, fmt: str, value: float) -> None:
        outstation, handler = _outstation()
        block = _ao_block(variation, fmt, [(5, value)])

        response = _send(outstation, build_direct_operate_request(objects=(block,), seq=0).to_bytes(), MASTER_A)

        assert _objects_on_wire(response) == _echo(block, [SUCCESS])
        assert handler.ao_direct == [(5, value)]
        assert handler.ao_selects == []
        assert handler.ao_operates == []
        assert outstation._state.selection_of(MASTER_A) is None
