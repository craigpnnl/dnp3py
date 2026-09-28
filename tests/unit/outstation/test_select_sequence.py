"""SELECT and OPERATE sequence rules in the outstation (craigpnnl/dnp3py#72).

IEEE 1815-2012 4.4.4.3 Rule 4 and Table 4-9: once a peer has a selection in
effect at sequence N, its next request decides what happens to it. A SELECT at
N with the same octets is a retry, one with other octets is discarded, and one
at another sequence starts a new selection. An OPERATE executes only at N+1
(mod 16) with the same octets; any other OPERATE, and any other request, ends
the selection. Another peer's requests never touch it.
"""

from __future__ import annotations

import time

import pytest

from dnp3.application.builder import (
    build_confirm_request,
    build_direct_operate_request,
    build_integrity_poll,
    build_operate_request,
    build_select_request,
    build_write_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId
from dnp3.outstation.state import OutstationStateManager, SelectState

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)

SUCCESS = CommandStatus.SUCCESS
NO_SELECT = CommandStatus.NO_SELECT
BLOCKED = CommandStatus.BLOCKED_OTHER_MASTER

_CROB_BODY_BYTES = 11
_QUALIFIER_SIZES = {0x17: 1, 0x28: 2}


class _RecordingHandler(DefaultCommandHandler):
    """Accepts every binary-output SELECT and OPERATE and records what it was given."""

    def __init__(self) -> None:
        super().__init__()
        self.selects: list[tuple[int, int]] = []
        self.operates: list[tuple[int, int, int]] = []

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.selects.append((index, on_time))
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.operates.append((index, on_time, select_sequence))
        return CommandResult.success()


def _crob_block(*points: tuple[int, int], qualifier: int = 0x17, status: int = 0) -> ObjectBlock:
    """g12v1 LATCH_ON, one object per (index, on_time)."""
    size = _QUALIFIER_SIZES[qualifier]
    data = bytearray(len(points).to_bytes(size, "little"))
    for index, on_time in points:
        data += index.to_bytes(size, "little") + bytes([int(ControlCode.LATCH_ON), 1])
        data += on_time.to_bytes(4, "little") + (0).to_bytes(4, "little") + bytes([status])
    return ObjectBlock(header=ObjectHeader(group=12, variation=1, qualifier=qualifier), data=bytes(data))


def _statuses(responses: list[ResponseFragment]) -> list[tuple[int, CommandStatus]]:
    """(index, status) for every object in the single echoed g12v1 block."""
    assert len(responses) == 1
    (block,) = responses[0].objects
    size = _QUALIFIER_SIZES[block.header.qualifier]
    data = block.data
    count = int.from_bytes(data[:size], "little")
    stride = size + _CROB_BODY_BYTES
    result = []
    for i in range(count):
        start = size + stride * i
        index = int.from_bytes(data[start : start + size], "little")
        result.append((index, CommandStatus(data[start + stride - 1])))
    return result


def _send(outstation: Outstation, peer: PeerId, request: RequestFragment) -> list[ResponseFragment]:
    return outstation.process_request(request.to_bytes(), peer=peer)


def _select(outstation: Outstation, peer: PeerId, seq: int, block: ObjectBlock) -> list[ResponseFragment]:
    return _send(outstation, peer, build_select_request(objects=(block,), seq=seq))


def _operate(outstation: Outstation, peer: PeerId, seq: int, block: ObjectBlock) -> list[ResponseFragment]:
    return _send(outstation, peer, build_operate_request(objects=(block,), seq=seq))


def _outstation(select_timeout: float = 10.0) -> tuple[Outstation, _RecordingHandler]:
    handler = _RecordingHandler()
    outstation = Outstation(config=OutstationConfig(select_timeout=select_timeout), handler=handler)
    outstation.database.add_binary_output(5)
    outstation.database.add_binary_output(6)
    return outstation, handler


POINT_5 = _crob_block((5, 1000))


class TestOperateSequence:
    """An OPERATE executes only at the selection's sequence plus one."""

    def test_operate_at_n_plus_2_is_refused_and_ends_the_selection(self) -> None:
        outstation, handler = _outstation()
        assert _statuses(_select(outstation, MASTER_A, 3, POINT_5)) == [(5, SUCCESS)]

        assert _statuses(_operate(outstation, MASTER_A, 5, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []

        assert _statuses(_operate(outstation, MASTER_A, 4, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []

    def test_identical_operate_repeated_at_n_plus_1_executes_once(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 7, POINT_5)

        assert _statuses(_operate(outstation, MASTER_A, 8, POINT_5)) == [(5, SUCCESS)]
        assert _statuses(_operate(outstation, MASTER_A, 8, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == [(5, 1000, 7)]

    def test_sequence_wraps_from_15_to_0(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 15, POINT_5)

        assert _statuses(_operate(outstation, MASTER_A, 0, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000, 15)]

    @pytest.mark.parametrize(
        "operate_block",
        [_crob_block((5, 1000), status=1), _crob_block((5, 1000), qualifier=0x28)],
        ids=["status-octet-differs", "qualifier-differs"],
    )
    def test_operate_with_other_octets_is_refused_and_ends_the_selection(self, operate_block: ObjectBlock) -> None:
        # Both variants carry the same point, control code and times, so only a
        # comparison of the whole octet string can tell them from the SELECT.
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 2, POINT_5)

        assert _statuses(_operate(outstation, MASTER_A, 3, operate_block)) == [(5, NO_SELECT)]
        assert handler.operates == []

        assert _statuses(_operate(outstation, MASTER_A, 3, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []


class TestSelectRetryDiscardOverride:
    """A second SELECT from the same peer is a retry, a discard or an override."""

    def test_retry_repeats_the_response_without_the_handler_or_a_new_timer(self) -> None:
        timeout = 0.5
        outstation, handler = _outstation(select_timeout=timeout)
        first = _select(outstation, MASTER_A, 4, POINT_5)
        assert _statuses(first) == [(5, SUCCESS)]

        time.sleep(timeout * 0.7)
        retry = _select(outstation, MASTER_A, 4, POINT_5)

        assert [r.to_bytes() for r in retry] == [r.to_bytes() for r in first]
        assert handler.selects == [(5, 1000)]

        # Past the original timer but not past one restarted by the retry.
        time.sleep(timeout * 0.7)
        assert _statuses(_operate(outstation, MASTER_A, 5, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []

    def test_same_sequence_with_other_octets_is_discarded(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 4, POINT_5)

        assert _select(outstation, MASTER_A, 4, _crob_block((5, 2000))) == []
        assert handler.selects == [(5, 1000)]

        assert _statuses(_operate(outstation, MASTER_A, 5, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000, 4)]

    def test_new_sequence_ends_the_whole_previous_selection(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)

        assert _statuses(_select(outstation, MASTER_A, 1, _crob_block((6, 6000)))) == [(6, SUCCESS)]
        assert _statuses(_select(outstation, MASTER_B, 0, _crob_block((5, 5000)))) == [(5, SUCCESS)]
        assert _statuses(_operate(outstation, MASTER_A, 2, _crob_block((6, 6000)))) == [(6, SUCCESS)]
        assert _statuses(_operate(outstation, MASTER_B, 1, _crob_block((5, 5000)))) == [(5, SUCCESS)]
        assert handler.operates == [(6, 6000, 1), (5, 5000, 0)]

    @pytest.mark.parametrize(("operate_seq", "expected"), [(1, NO_SELECT), (2, SUCCESS)], ids=["old-n+1", "new-n+1"])
    def test_same_octets_at_a_new_sequence_is_a_new_selection(self, operate_seq: int, expected: CommandStatus) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)

        assert _statuses(_select(outstation, MASTER_A, 1, POINT_5)) == [(5, SUCCESS)]
        assert handler.selects == [(5, 1000), (5, 1000)]

        assert _statuses(_operate(outstation, MASTER_A, operate_seq, POINT_5)) == [(5, expected)]
        assert handler.operates == ([(5, 1000, 1)] if expected == SUCCESS else [])

    def test_select_that_stores_nothing_leaves_no_selection_to_retry(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_B, 0, _crob_block((5, 5000)))
        assert _statuses(_select(outstation, MASTER_A, 3, POINT_5)) == [(5, BLOCKED)]
        _operate(outstation, MASTER_B, 1, _crob_block((5, 5000)))

        assert _statuses(_select(outstation, MASTER_A, 3, POINT_5)) == [(5, SUCCESS)]
        assert _statuses(_operate(outstation, MASTER_A, 4, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 5000, 0), (5, 1000, 3)]

    def test_expired_selection_is_not_retried(self) -> None:
        timeout = 0.2
        outstation, handler = _outstation(select_timeout=timeout)
        _select(outstation, MASTER_A, 4, POINT_5)

        time.sleep(timeout * 1.5)
        assert _statuses(_select(outstation, MASTER_A, 4, POINT_5)) == [(5, SUCCESS)]
        assert handler.selects == [(5, 1000), (5, 1000)]
        assert _statuses(_operate(outstation, MASTER_A, 5, POINT_5)) == [(5, SUCCESS)]

    def test_every_point_shares_the_selections_timer(self) -> None:
        timeout = 0.4
        outstation, handler = _outstation(select_timeout=timeout)
        accept_select = handler.select_binary_output

        def select_point_6_slowly(
            index: int, code: ControlCode, count: int, on_time: int, off_time: int
        ) -> CommandResult:
            if index == 6:
                time.sleep(timeout * 0.75)
            return accept_select(index, code, count, on_time, off_time)

        handler.select_binary_output = select_point_6_slowly  # type: ignore[method-assign]
        both = _crob_block((5, 1000), (6, 6000))
        assert _statuses(_select(outstation, MASTER_A, 0, both)) == [(5, SUCCESS), (6, SUCCESS)]

        # Past the timer started with the SELECT, though not yet past the moment point 6 was accepted.
        time.sleep(timeout * 0.5)
        assert _statuses(_operate(outstation, MASTER_A, 1, both)) == [(5, NO_SELECT), (6, NO_SELECT)]
        assert handler.operates == []


class TestOtherRequestsBetweenSelectAndOperate:
    """Any other request from the selecting peer ends its selection, except CONFIRM."""

    @pytest.mark.parametrize(
        "between",
        [
            build_integrity_poll(seq=1),
            build_write_request(objects=(), seq=1),
            build_direct_operate_request(objects=(_crob_block((6, 6000)),), seq=1),
            RequestFragment(
                header=RequestHeader.build(function=FunctionCode.DIRECT_OPERATE_NO_ACK, seq=1),
                objects=(_crob_block((6, 6000)),),
            ),
        ],
        ids=["read", "write", "direct-operate", "direct-operate-no-ack"],
    )
    def test_other_request_ends_the_selection(self, between: RequestFragment) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)
        _send(outstation, MASTER_A, between)

        assert _statuses(_operate(outstation, MASTER_A, 1, POINT_5)) == [(5, NO_SELECT)]
        assert [op for op in handler.operates if op[0] == 5] == []

    @pytest.mark.parametrize(
        "fragment",
        [bytes([0xC0]), bytes([0xC1, 0x70])],
        ids=["shorter-than-a-header", "unknown-function-code"],
    )
    def test_request_that_fails_to_parse_ends_the_selection(self, fragment: bytes) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)
        outstation.process_request(fragment, peer=MASTER_A)

        assert _statuses(_operate(outstation, MASTER_A, 1, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []

    def test_another_peers_unparseable_request_never_ends_the_selection(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)
        outstation.process_request(bytes([0xC1, 0x70]), peer=MASTER_B)

        assert _statuses(_operate(outstation, MASTER_A, 1, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000, 0)]

    def test_confirm_does_not_end_the_selection(self) -> None:
        """A CONFIRM from the selecting master only acknowledges an earlier response.

        It carries no request of its own, so it is not treated as the request
        that follows the SELECT; the operator decided the selection survives it.
        """
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)
        _send(outstation, MASTER_A, build_confirm_request(seq=0))

        assert _statuses(_operate(outstation, MASTER_A, 1, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000, 0)]

    @pytest.mark.parametrize(
        "intrusion",
        [
            build_integrity_poll(seq=9),
            build_operate_request(objects=(POINT_5,), seq=9),
            build_operate_request(objects=(POINT_5,), seq=1),
            build_select_request(objects=(_crob_block((6, 6000)),), seq=0),
            build_select_request(objects=(POINT_5,), seq=0),
            build_confirm_request(seq=0),
        ],
        ids=["read", "operate", "operate-at-n+1", "select-other-point", "select-same-octets", "confirm"],
    )
    def test_another_peers_request_never_ends_the_selection(self, intrusion: RequestFragment) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, 0, POINT_5)
        _send(outstation, MASTER_B, intrusion)

        assert _statuses(_operate(outstation, MASTER_A, 1, POINT_5)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000, 0)]


class TestSelectionWithoutARequest:
    """A selection stored directly, with no SELECT request seen, is never operated by one."""

    def test_add_select_alone_is_not_executed_through_process_request(self) -> None:
        outstation, handler = _outstation()
        outstation._state.add_select(
            SelectState(index=5, is_binary=True, control_code=ControlCode.LATCH_ON, on_time=1000, sequence=0)
        )

        assert _statuses(_operate(outstation, UNSPECIFIED_PEER, 1, POINT_5)) == [(5, NO_SELECT)]
        assert handler.operates == []


class TestSelectionStore:
    """The store keys a peer's points by object group as well as index."""

    def test_group_12_and_group_41_at_one_index_do_not_collide(self) -> None:
        manager = OutstationStateManager()
        binary = SelectState(index=5, is_binary=True)
        analog = SelectState(index=5, is_binary=False, analog_value=2.5)
        manager.add_select(binary, peer=MASTER_A)
        manager.add_select(analog, peer=MASTER_A, group=41)

        assert manager.get_select(5, peer=MASTER_A) is binary
        assert manager.get_select(5, peer=MASTER_A, group=41) is analog
        assert manager.held_by_other_peer(5, MASTER_B, 10.0, group=41) is True

        manager.remove_select(5, peer=MASTER_A, group=41)
        assert manager.get_select(5, peer=MASTER_A, group=41) is None
        assert manager.get_select(5, peer=MASTER_A) is binary
        assert manager.held_by_other_peer(5, MASTER_B, 10.0, group=41) is False
        assert manager.held_by_other_peer(5, MASTER_B, 10.0) is True

    def test_removing_the_last_point_ends_the_peers_selection(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_A)
        assert manager.selection_of(MASTER_A) is not None

        manager.remove_select(5, peer=MASTER_A)

        assert manager.selection_of(MASTER_A) is None

    def test_begin_selection_replaces_the_peers_record_only(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_A)
        kept = SelectState(index=5, is_binary=True)
        manager.add_select(kept, peer=MASTER_B)

        manager.begin_selection(MASTER_A, 3, b"\x0c\x01")

        selection = manager.selection_of(MASTER_A)
        assert selection is not None
        assert (selection.sequence, selection.body, selection.response, selection.points) == (3, b"\x0c\x01", None, {})
        assert manager.get_select(5, peer=MASTER_B) is kept

    def test_terminate_ends_only_that_peers_selection(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_A)
        kept = SelectState(index=6, is_binary=True)
        manager.add_select(kept, peer=MASTER_B)

        manager.terminate(MASTER_A)

        assert manager.selection_of(MASTER_A) is None
        assert manager.get_select(5, peer=MASTER_A) is None
        assert manager.get_select(6, peer=MASTER_B) is kept

    def test_clear_expired_selects_drops_an_emptied_record(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True, timestamp=time.monotonic() - 20.0), peer=MASTER_A)

        manager.clear_expired_selects(10.0)

        assert manager.selection_of(MASTER_A) is None
