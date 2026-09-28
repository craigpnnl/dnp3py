"""Unit tests for peer identity plumbing (craigpnnl/dnp3py#72 slice 1).

Peer identity is threaded from the TCP runner's frame source and a
per-connection counter into Outstation.process_request(), so a later slice
can key SELECT/OPERATE state per peer. This slice changes no SELECT/OPERATE
behaviour: it proves the identity reaches the outstation unchanged for
existing single-peer callers, and distinctly for two connections.
"""

from __future__ import annotations

import pytest

from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId


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
