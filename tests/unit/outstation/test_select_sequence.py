"""The outstation's selection store (craigpnnl/dnp3py#72).

Each peer has at most one selection in effect, holding its points by object
group as well as index.
"""

from __future__ import annotations

import time

from dnp3.outstation.peer import PeerId
from dnp3.outstation.state import OutstationStateManager, SelectState

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)


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
