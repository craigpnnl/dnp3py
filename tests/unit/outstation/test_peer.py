"""Unit tests for peer identity plumbing (craigpnnl/dnp3py#72 slice 1).

Peer identity is threaded from the TCP runner's frame source and a
per-connection counter into Outstation.process_request(), so a later slice
can key SELECT/OPERATE state per peer. This slice changes no SELECT/OPERATE
behaviour: it proves the identity reaches the outstation unchanged for
existing single-peer callers, and distinctly for two connections.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.database import Database
from dnp3.datalink.builder import build_unconfirmed_user_data
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId
from dnp3.outstation.tcp_runner import OutstationTcpRunner
from dnp3.transport.segment import TransportSegment
from dnp3.transport_io.simulator import SimulatorChannel, create_channel_pair

MASTER_ADDR = 3
OUTSTATION_ADDR = 1


def _make_outstation() -> Outstation:
    config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
    return Outstation(config=config, database=Database())


def _build_request_frame(master_addr: int, outstation_addr: int, request_bytes: bytes) -> bytes:
    """Build a complete data link frame containing a DNP3 request."""
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request_bytes)
    frame = build_unconfirmed_user_data(
        destination=outstation_addr,
        source=master_addr,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


async def _drain(channel: SimulatorChannel, timeout: float = 1.0) -> None:
    """Read and discard the outstation's response so the handler isn't blocked."""
    with contextlib.suppress(TimeoutError, Exception):
        while True:
            chunk = await asyncio.wait_for(channel.read(4096), timeout=timeout)
            if not chunk:
                break
            timeout = 0.2


class TestPeerId:
    """PeerId itself: frozen, comparable by value, and the default constant."""

    def test_equal_by_value(self) -> None:
        assert PeerId(source=3, connection=1) == PeerId(source=3, connection=1)

    def test_distinct_connection_is_a_different_peer(self) -> None:
        assert PeerId(source=3, connection=1) != PeerId(source=3, connection=2)

    def test_frozen(self) -> None:
        peer = PeerId(source=3, connection=1)
        with pytest.raises(AttributeError):
            peer.source = 4  # type: ignore[misc]

    def test_unspecified_peer_has_no_connection(self) -> None:
        assert UNSPECIFIED_PEER.connection is None


class TestProcessRequestDefaultPeer:
    """process_request(data) with no peer keyword resolves to UNSPECIFIED_PEER."""

    def test_no_peer_argument_resolves_to_unspecified(self) -> None:
        outstation = _make_outstation()
        request_bytes = build_integrity_poll(seq=0).to_bytes()
        with patch.object(
            outstation,
            "_process_request_fragment",
            wraps=outstation._process_request_fragment,
        ) as spy:
            outstation.process_request(request_bytes)
        received_peer = spy.call_args[0][1]
        assert received_peer == UNSPECIFIED_PEER

    def test_explicit_peer_argument_is_forwarded_unchanged(self) -> None:
        outstation = _make_outstation()
        request_bytes = build_integrity_poll(seq=0).to_bytes()
        peer = PeerId(source=7, connection=None)
        with patch.object(
            outstation,
            "_process_request_fragment",
            wraps=outstation._process_request_fragment,
        ) as spy:
            outstation.process_request(request_bytes, peer=peer)
        received_peer = spy.call_args[0][1]
        assert received_peer == peer


class TestRunnerAssignsConnectionIds:
    """OutstationTcpRunner passes a PeerId built from the frame source and a
    per-runner connection counter into process_request, on every request."""

    @pytest.mark.asyncio
    async def test_successive_connections_get_incrementing_connection_ids(self) -> None:
        outstation = _make_outstation()
        runner = OutstationTcpRunner(outstation=outstation)
        request_bytes = build_integrity_poll(seq=0).to_bytes()

        with patch.object(outstation, "process_request", wraps=outstation.process_request) as spy:
            for expected_conn_id in (1, 2):
                master_ch, outstation_ch = create_channel_pair()
                await master_ch.open()
                await outstation_ch.open()
                await master_ch.write_all(_build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request_bytes))

                task = asyncio.create_task(runner._handle_connection(outstation_ch))
                await _drain(master_ch)

                await master_ch.close()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

                received_peer = spy.call_args.kwargs["peer"]
                assert received_peer == PeerId(source=MASTER_ADDR, connection=expected_conn_id)
