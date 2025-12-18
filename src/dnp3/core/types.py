"""Core type definitions for DNP3 protocol.

Uses NewType for type safety and dataclasses for structured data.
"""

from dataclasses import dataclass
from typing import NewType

# DNP3 addresses are 16-bit unsigned integers
Address = NewType("Address", int)

# Maximum valid address (0xFFFE, since 0xFFFF is broadcast)
MAX_ADDRESS: Address = Address(0xFFFE)

# Broadcast address for all stations
BROADCAST_ADDRESS: Address = Address(0xFFFF)

# Point index (16-bit unsigned)
PointIndex = NewType("PointIndex", int)

# Sequence numbers
AppSequence = NewType("AppSequence", int)  # 4-bit (0-15)
TransportSequence = NewType("TransportSequence", int)  # 6-bit (0-63)


@dataclass(frozen=True, slots=True)
class LinkAddresses:
    """Data link layer source and destination addresses."""

    source: Address
    destination: Address
