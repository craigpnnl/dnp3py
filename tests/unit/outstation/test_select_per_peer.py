"""Per-peer SELECT state in the outstation (craigpnnl/dnp3py#72).

A selection belongs to the peer that made it: another peer can neither
operate it, overwrite it nor clear it. A SELECT on a point another peer holds
returns BLOCKED_OTHER_MASTER, and a connection's selections are released when
that connection closes.
"""

from __future__ import annotations

import time

from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId
from dnp3.outstation.state import OutstationStateManager, SelectState

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
