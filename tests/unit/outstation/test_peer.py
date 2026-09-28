"""Unit tests for peer identity plumbing (craigpnnl/dnp3py#72 slice 1).

Peer identity is threaded from the TCP runner's frame source and a
per-connection counter into Outstation.process_request(), so a later slice
can key SELECT/OPERATE state per peer. This slice changes no SELECT/OPERATE
behaviour: it proves the identity reaches the outstation unchanged for
existing single-peer callers, and distinctly for two connections.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.database import Database
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId

MASTER_ADDR = 3
OUTSTATION_ADDR = 1


def _make_outstation() -> Outstation:
    config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
    return Outstation(config=config, database=Database())


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
