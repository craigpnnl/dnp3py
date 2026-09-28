"""Per-peer SELECT state in the outstation (craigpnnl/dnp3py#72).

A selection belongs to the peer that made it: another peer can neither
operate it, overwrite it nor clear it. A SELECT on a point another peer holds
returns BLOCKED_OTHER_MASTER, and a connection's selections are released when
that connection closes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import pytest

from dnp3.application.builder import build_operate_request, build_select_request
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.database import Database
from dnp3.datalink.builder import build_unconfirmed_user_data
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId
from dnp3.outstation.state import OutstationStateManager, SelectState
from dnp3.outstation.tcp_runner import OutstationTcpRunner
from dnp3.transport.segment import TransportSegment
from dnp3.transport_io.channel import ChannelError
from dnp3.transport_io.simulator import SimulatorChannel, create_channel_pair

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)
TIMEOUT = 10.0


class TestSelectStoreIsPerPeer:
    """OutstationStateManager keeps one selection per (peer, index)."""

    def test_same_index_from_two_peers_is_two_selections(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True, on_time=1000), peer=MASTER_A)
        manager.add_select(SelectState(index=5, is_binary=True, on_time=5000), peer=MASTER_B)

        selection_a = manager.get_select(5, peer=MASTER_A)
        selection_b = manager.get_select(5, peer=MASTER_B)
        assert selection_a is not None
        assert selection_b is not None
        assert selection_a.on_time == 1000
        assert selection_b.on_time == 5000

    def test_remove_select_leaves_the_other_peers_selection(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True, on_time=1000), peer=MASTER_A)
        manager.add_select(SelectState(index=5, is_binary=True, on_time=5000), peer=MASTER_B)

        manager.remove_select(5, peer=MASTER_A)

        assert manager.get_select(5, peer=MASTER_A) is None
        selection_b = manager.get_select(5, peer=MASTER_B)
        assert selection_b is not None
        assert selection_b.on_time == 5000

    def test_no_peer_argument_is_the_unspecified_peer(self) -> None:
        manager = OutstationStateManager()
        select = SelectState(index=5, is_binary=True)
        manager.add_select(select)

        assert manager.get_select(5, peer=UNSPECIFIED_PEER) is select
        assert manager.get_select(5, peer=MASTER_A) is None

    def test_same_source_on_another_connection_is_another_peer(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_A)

        same_source_other_connection = PeerId(source=MASTER_A.source, connection=7)
        assert manager.get_select(5, peer=same_source_other_connection) is None

    def test_held_by_other_peer(self) -> None:
        manager = OutstationStateManager()
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_B)

        assert manager.held_by_other_peer(5, MASTER_A, TIMEOUT) is True
        assert manager.held_by_other_peer(5, MASTER_B, TIMEOUT) is False
        assert manager.held_by_other_peer(6, MASTER_A, TIMEOUT) is False

    def test_an_expired_selection_holds_nothing(self) -> None:
        manager = OutstationStateManager()
        stale = SelectState(index=5, is_binary=True, timestamp=time.monotonic() - 2 * TIMEOUT)
        manager.add_select(stale, peer=MASTER_B)

        assert manager.held_by_other_peer(5, MASTER_A, TIMEOUT) is False

    def test_clear_expired_selects_covers_every_peer(self) -> None:
        manager = OutstationStateManager()
        stale = SelectState(index=5, is_binary=True, timestamp=time.monotonic() - 2 * TIMEOUT)
        fresh = SelectState(index=5, is_binary=True)
        manager.add_select(stale, peer=MASTER_A)
        manager.add_select(fresh, peer=MASTER_B)

        manager.clear_expired_selects(TIMEOUT)

        assert manager.get_select(5, peer=MASTER_A) is None
        assert manager.get_select(5, peer=MASTER_B) is fresh

    def test_release_connection_drops_only_that_connections_selections(self) -> None:
        manager = OutstationStateManager()
        second_source_same_connection = PeerId(source=4, connection=MASTER_A.connection)
        kept_b = SelectState(index=5, is_binary=True)
        kept_unspecified = SelectState(index=6, is_binary=True)
        manager.add_select(SelectState(index=5, is_binary=True), peer=MASTER_A)
        manager.add_select(SelectState(index=6, is_binary=True), peer=second_source_same_connection)
        manager.add_select(kept_b, peer=MASTER_B)
        manager.add_select(kept_unspecified)

        assert MASTER_A.connection is not None
        manager.release_connection(MASTER_A.connection)

        assert manager.get_select(5, peer=MASTER_A) is None
        assert manager.get_select(6, peer=second_source_same_connection) is None
        assert manager.get_select(5, peer=MASTER_B) is kept_b
        assert manager.get_select(6) is kept_unspecified


class _RecordingHandler(DefaultCommandHandler):
    """Accepts every binary-output SELECT and OPERATE and records (index, on_time)."""

    def __init__(self) -> None:
        super().__init__()
        self.selects: list[tuple[int, int]] = []
        self.operates: list[tuple[int, int]] = []

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.selects.append((index, on_time))
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.operates.append((index, on_time))
        return CommandResult.success()


def _crob_block(*points: tuple[int, int]) -> ObjectBlock:
    """g12v1, qualifier 0x17, LATCH_ON, one object per (index, on_time)."""
    data = bytearray([len(points)])
    for index, on_time in points:
        data += bytes([index, int(ControlCode.LATCH_ON), 1])
        data += on_time.to_bytes(4, "little") + (0).to_bytes(4, "little") + bytes([0])
    return ObjectBlock(header=ObjectHeader(group=12, variation=1, qualifier=0x17), data=bytes(data))


def _statuses(responses: list[ResponseFragment]) -> list[tuple[int, CommandStatus]]:
    """(index, status) for every object in the single echoed g12v1 block."""
    assert len(responses) == 1
    (block,) = responses[0].objects
    data = block.data
    return [(data[1 + 12 * i], CommandStatus(data[12 + 12 * i])) for i in range(data[0])]


def _select(outstation: Outstation, peer: PeerId | None, *points: tuple[int, int]) -> list[tuple[int, CommandStatus]]:
    request = build_select_request(objects=(_crob_block(*points),), seq=0)
    return _statuses(outstation.process_request(request.to_bytes(), peer=peer))


def _operate(outstation: Outstation, peer: PeerId | None, *points: tuple[int, int]) -> list[tuple[int, CommandStatus]]:
    request = build_operate_request(objects=(_crob_block(*points),), seq=1)
    return _statuses(outstation.process_request(request.to_bytes(), peer=peer))


def _outstation() -> tuple[Outstation, _RecordingHandler]:
    handler = _RecordingHandler()
    outstation = Outstation(handler=handler)
    outstation.database.add_binary_output(5)
    outstation.database.add_binary_output(6)
    return outstation, handler


SUCCESS = CommandStatus.SUCCESS
NO_SELECT = CommandStatus.NO_SELECT
BLOCKED = CommandStatus.BLOCKED_OTHER_MASTER


class TestTwoPeersSelectAndOperate:
    """SELECT and OPERATE through process_request with two peers."""

    def test_each_peer_operates_with_its_own_on_time(self) -> None:
        outstation, handler = _outstation()

        assert _select(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, BLOCKED)]
        assert _operate(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]
        assert _operate(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]

        assert handler.selects == [(5, 1000), (5, 5000)]
        assert handler.operates == [(5, 1000), (5, 5000)]

    def test_concurrent_selections_on_two_points_each_operate(self) -> None:
        outstation, handler = _outstation()

        assert _select(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert _select(outstation, MASTER_B, (6, 5000)) == [(6, SUCCESS)]
        assert _operate(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert _operate(outstation, MASTER_B, (6, 5000)) == [(6, SUCCESS)]

        assert handler.operates == [(5, 1000), (6, 5000)]

    @pytest.mark.parametrize("intruder_on_time", [1000, 5000], ids=["same-params", "different-params"])
    def test_operate_from_another_peer_is_no_select_and_holder_still_operates(self, intruder_on_time: int) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, (5, 1000))

        assert _operate(outstation, MASTER_B, (5, intruder_on_time)) == [(5, NO_SELECT)]
        assert handler.operates == []

        assert _operate(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000)]


class TestSelectOnPointAnotherPeerHolds:
    """A SELECT on a point another peer holds returns BLOCKED_OTHER_MASTER (17)."""

    def test_returns_17_skips_the_handler_and_leaves_the_holder_armed(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, (5, 1000))

        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, BLOCKED)]
        assert int(BLOCKED) == 17
        assert handler.selects == [(5, 1000)]
        held = outstation._state.get_select(5, peer=MASTER_A)
        assert held is not None
        assert held.on_time == 1000
        assert outstation._state.get_select(5, peer=MASTER_B) is None

        assert _operate(outstation, MASTER_A, (5, 1000)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000)]

    def test_status_is_per_object(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, (5, 1000))

        assert _select(outstation, MASTER_B, (5, 5000), (6, 6000)) == [(5, BLOCKED), (6, SUCCESS)]
        assert handler.selects == [(5, 1000), (6, 6000)]

    def test_an_expired_holder_does_not_block(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, (5, 1000))
        held = outstation._state.get_select(5, peer=MASTER_A)
        assert held is not None
        held.timestamp = time.monotonic() - 2 * outstation.config.select_timeout

        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]
        assert _operate(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 5000)]

    def test_select_purges_expired_selections_from_every_peer(self) -> None:
        outstation, _ = _outstation()
        expired_at = time.monotonic() - 2 * outstation.config.select_timeout
        abandoned: list[PeerId] = []
        for source in range(10, 15):
            peer = PeerId(source=source, connection=1)
            assert _select(outstation, peer, (5, 1000)) == [(5, SUCCESS)]
            held = outstation._state.get_select(5, peer=peer)
            assert held is not None
            held.timestamp = expired_at
            abandoned.append(peer)

        live = PeerId(source=15, connection=1)
        assert _select(outstation, live, (5, 1000)) == [(5, SUCCESS)]

        for peer in abandoned:
            assert outstation._state.get_select(5, peer=peer) is None
        assert outstation._state.get_select(5, peer=live) is not None

    def test_the_holder_may_select_its_own_point_again(self) -> None:
        outstation, handler = _outstation()
        _select(outstation, MASTER_A, (5, 1000))

        assert _select(outstation, MASTER_A, (5, 2000)) == [(5, SUCCESS)]
        assert _operate(outstation, MASTER_A, (5, 2000)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 2000)]


class TestSameSourceOnTwoConnections:
    """Two connections carrying the same link source address are two peers."""

    def test_selection_on_connection_1_is_no_select_on_connection_2(self) -> None:
        outstation, handler = _outstation()
        first = PeerId(source=3, connection=1)
        second = PeerId(source=3, connection=2)
        _select(outstation, first, (5, 1000))

        assert _operate(outstation, second, (5, 1000)) == [(5, NO_SELECT)]
        assert handler.operates == []
        assert _operate(outstation, first, (5, 1000)) == [(5, SUCCESS)]
        assert handler.operates == [(5, 1000)]

    def test_select_on_connection_2_is_blocked_by_connection_1(self) -> None:
        outstation, handler = _outstation()
        first = PeerId(source=3, connection=1)
        second = PeerId(source=3, connection=2)
        assert _select(outstation, first, (5, 1000)) == [(5, SUCCESS)]

        assert _select(outstation, second, (5, 1000)) == [(5, BLOCKED)]
        assert handler.selects == [(5, 1000)]
        assert outstation._state.get_select(5, peer=second) is None


class TestSingleMasterUnchanged:
    """A caller that passes no peer keeps the behaviour it had before peers existed."""

    def test_reselect_without_a_peer_replaces_the_selection(self) -> None:
        outstation, handler = _outstation()

        assert _select(outstation, None, (5, 1000)) == [(5, SUCCESS)]
        assert _select(outstation, None, (5, 2000)) == [(5, SUCCESS)]
        assert _operate(outstation, None, (5, 1000)) == [(5, NO_SELECT)]
        assert _select(outstation, None, (5, 3000)) == [(5, SUCCESS)]
        assert _operate(outstation, None, (5, 3000)) == [(5, SUCCESS)]

        assert handler.selects == [(5, 1000), (5, 2000), (5, 3000)]
        assert handler.operates == [(5, 3000)]


OUTSTATION_ADDR = 1


def _frame(source: int, request_bytes: bytes) -> bytes:
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request_bytes)
    frame = build_unconfirmed_user_data(
        destination=OUTSTATION_ADDR,
        source=source,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


async def _drain(channel: SimulatorChannel, timeout: float = 1.0) -> None:
    with contextlib.suppress(TimeoutError):
        while True:
            chunk = await asyncio.wait_for(channel.read(4096), timeout=timeout)
            if not chunk:
                break
            timeout = 0.2


class TestRunnerReleasesSelectionsOnDisconnect:
    """When a connection closes, the runner releases every selection made on it."""

    @pytest.mark.asyncio
    async def test_closed_connection_releases_its_selection(self) -> None:
        handler = _RecordingHandler()
        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_A.source)
        outstation = Outstation(config=config, database=Database(), handler=handler)
        outstation.database.add_binary_output(5)
        outstation.database.add_binary_output(6)
        runner = OutstationTcpRunner(outstation=outstation)
        other_connection = PeerId(source=MASTER_B.source, connection=99)
        assert _select(outstation, other_connection, (6, 6000)) == [(6, SUCCESS)]

        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()
        task = asyncio.create_task(runner._handle_connection(outstation_ch))
        select = build_select_request(objects=(_crob_block((5, 1000)),), seq=0)
        await master_ch.write_all(_frame(MASTER_A.source, select.to_bytes()))
        await _drain(master_ch)

        assert handler.selects == [(6, 6000), (5, 1000)]
        assert outstation._state.get_select(5, peer=MASTER_A) is not None
        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, BLOCKED)]

        await master_ch.close()
        await asyncio.wait_for(task, timeout=2.0)

        assert outstation._state.get_select(5, peer=MASTER_A) is None
        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]
        assert outstation._state.get_select(6, peer=other_connection) is not None


class _ScriptedChannel:
    """Returns each scripted read in turn, raising any exception it holds; then EOF."""

    def __init__(self, *reads: bytes | Exception) -> None:
        self._reads = list(reads)
        self.closed = 0

    async def read(self, _max_bytes: int) -> bytes:
        if not self._reads:
            return b""
        item = self._reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def write_all(self, _data: bytes) -> None:
        return None

    async def close(self) -> None:
        self.closed += 1


class _ReleaseFails(Outstation):
    def release_connection(self, connection: int) -> None:
        raise RuntimeError("release failed")


class TestRunnerCloseWhenReleaseRaises:
    """A failing release does not leave the connection open or unlogged."""

    @pytest.mark.asyncio
    async def test_channel_still_closes_and_the_error_surfaces(self, caplog: pytest.LogCaptureFixture) -> None:
        runner = OutstationTcpRunner(outstation=_ReleaseFails())
        channel = _ScriptedChannel()

        with (
            caplog.at_level(logging.INFO, logger="dnp3.outstation.tcp_runner"),
            pytest.raises(RuntimeError, match="release failed"),
        ):
            await runner._handle_connection(channel)

        assert channel.closed == 1
        assert "Connection closed" in caplog.messages


class TestRunnerReleasesOnChannelError:
    """A connection that ends in a transport error releases its selections too."""

    @pytest.mark.asyncio
    async def test_selection_is_released_after_a_channel_error(self) -> None:
        handler = _RecordingHandler()
        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_A.source)
        outstation = Outstation(config=config, database=Database(), handler=handler)
        outstation.database.add_binary_output(5)
        select = build_select_request(objects=(_crob_block((5, 1000)),), seq=0)
        channel = _ScriptedChannel(_frame(MASTER_A.source, select.to_bytes()), ChannelError("reset by peer"))

        await OutstationTcpRunner(outstation=outstation)._handle_connection(channel)

        assert handler.selects == [(5, 1000)]
        assert channel.closed == 1
        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, SUCCESS)]


class TestTwoRunnersOverOneOutstation:
    """Connection ids stay unique when several runners serve one outstation."""

    @pytest.mark.asyncio
    async def test_same_source_on_another_runner_cannot_touch_the_selection(self) -> None:
        handler = _RecordingHandler()
        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_A.source)
        outstation = Outstation(config=config, database=Database(), handler=handler)
        outstation.database.add_binary_output(5)
        first_master, first_task = await _connect(OutstationTcpRunner(outstation=outstation))
        second_master, second_task = await _connect(OutstationTcpRunner(outstation=outstation))

        select = build_select_request(objects=(_crob_block((5, 1000)),), seq=0)
        await first_master.write_all(_frame(MASTER_A.source, select.to_bytes()))
        await _drain(first_master)
        operate = build_operate_request(objects=(_crob_block((5, 1000)),), seq=1)
        await second_master.write_all(_frame(MASTER_A.source, operate.to_bytes()))
        await _drain(second_master)

        assert handler.operates == []

        await second_master.close()
        await asyncio.wait_for(second_task, timeout=2.0)

        assert _select(outstation, MASTER_B, (5, 5000)) == [(5, BLOCKED)]
        await first_master.write_all(_frame(MASTER_A.source, operate.to_bytes()))
        await _drain(first_master)
        assert handler.operates == [(5, 1000)]

        await first_master.close()
        await asyncio.wait_for(first_task, timeout=2.0)


async def _connect(runner: OutstationTcpRunner) -> tuple[SimulatorChannel, asyncio.Task[None]]:
    master_ch, outstation_ch = create_channel_pair()
    await master_ch.open()
    await outstation_ch.open()
    return master_ch, asyncio.create_task(runner._handle_connection(outstation_ch))
