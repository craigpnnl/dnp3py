"""Peer identity for outstation requests (craigpnnl/dnp3py#72).

An outstation can serve more than one master, whether through distinct
link-layer source addresses or distinct transport connections. ``PeerId``
names the peer a request came from so per-peer state (SELECT/OPERATE
arming) can later be isolated between peers instead of shared.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["UNSPECIFIED_PEER", "PeerId"]


@dataclass(frozen=True, slots=True)
class PeerId:
    """Identifies the master that sent a request.

    ``connection`` distinguishes two masters that share one ``source``
    address on separate transport connections; it is ``None`` when the
    transport is not connection-oriented.
    """

    source: int
    connection: int | None


# The peer for a caller that does not identify one: every pre-#72 caller,
# and any single-master deployment that never passes `peer` explicitly.
UNSPECIFIED_PEER = PeerId(source=-1, connection=None)
