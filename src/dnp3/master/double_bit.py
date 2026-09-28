"""Double-bit binary input values and their handler callback, per IEEE 1815-2012 A.4.

A double-bit point reports one of four states rather than a bool, so it is
delivered on its own callback instead of on ``SOEHandler.on_binary_input``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from dnp3.core.flags import DoubleBitState
from dnp3.master.handler import ResponseInfo

__all__ = [
    "DOUBLE_BIT_FLAGS_MASK",
    "DoubleBitInputHandler",
    "DoubleBitValue",
    "deliver_double_bit_input",
    "double_bit_state",
    "unpack_double_bit_states",
]

# A.4.2.2.2: six flag bits, then the UINT2 state in bits 7 and 6.
DOUBLE_BIT_FLAGS_MASK = 0x3F
_STATE_SHIFT = 6
_STATE_MASK = 0x3

_POINTS_PER_OCTET = 4


@dataclass(frozen=True)
class DoubleBitValue:
    """Double-bit binary input value from a response.

    Attributes:
        index: Point index.
        state: One of the four double-bit states.
        quality: Flag bits 0 to 5, with the state bits cleared.
        timestamp: Event timestamp if available.
    """

    index: int
    state: DoubleBitState
    quality: int = 0
    timestamp: datetime | None = None


@runtime_checkable
class DoubleBitInputHandler(Protocol):
    """A handler that accepts double-bit binary input values.

    Separate from ``SOEHandler`` so existing handlers need no new method; a
    handler without this callback is not given double-bit values, and nothing
    reports the drop yet (#111). On Python 3.12 and later the callback must be
    found without ``__getattr__``, so a handler that forwards calls that way
    also receives none.
    """

    def on_double_bit_input(self, values: list[DoubleBitValue], info: ResponseInfo) -> None:
        """Called when double-bit binary input values are received.

        Args:
            values: List of double-bit binary input values.
            info: Response information.
        """
        ...


def double_bit_state(flags: int) -> DoubleBitState:
    """The state carried in bits 7 and 6 of a double-bit flag octet (A.4.2.2.2)."""
    return DoubleBitState((flags >> _STATE_SHIFT) & _STATE_MASK)


def unpack_double_bit_states(payload: bytes, count: int) -> list[DoubleBitState]:
    """Read `count` packed double-bit states, first point in bits 1 and 0 (A.4.1.2.2).

    Padding in the last octet is ignored, and reading stops at the end of the
    payload if it holds fewer than `count` points.
    """
    states: list[DoubleBitState] = []
    for ordinal in range(count):
        octet_index, slot = divmod(ordinal, _POINTS_PER_OCTET)
        if octet_index >= len(payload):
            break
        states.append(DoubleBitState((payload[octet_index] >> (2 * slot)) & _STATE_MASK))
    return states


def deliver_double_bit_input(handler: object, values: list[DoubleBitValue], info: ResponseInfo) -> None:
    """Hand values to a handler that implements `DoubleBitInputHandler`; others get nothing."""
    if isinstance(handler, DoubleBitInputHandler):
        handler.on_double_bit_input(values, info)
