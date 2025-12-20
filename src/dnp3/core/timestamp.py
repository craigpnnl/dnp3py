"""DNP3 timestamp handling per IEEE 1815-2012.

DNP3 uses 48-bit (6 byte) timestamps representing milliseconds since
the Unix epoch (1970-01-01 00:00:00 UTC).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

# Milliseconds per second
_MS_PER_SECOND = 1000

# Size of DNP3 timestamp in bytes (48 bits = 6 bytes)
TIMESTAMP_SIZE = 6


@dataclass(frozen=True, slots=True)
class DNP3Timestamp:
    """DNP3 48-bit timestamp (milliseconds since Unix epoch).

    Timestamps are stored as unsigned 48-bit integers representing
    milliseconds since 1970-01-01 00:00:00 UTC.
    """

    milliseconds: int

    def to_datetime(self) -> datetime:
        """Convert to Python datetime in UTC.

        Returns:
            datetime object in UTC timezone.
        """
        seconds = self.milliseconds // _MS_PER_SECOND
        micros = (self.milliseconds % _MS_PER_SECOND) * _MS_PER_SECOND
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=micros)

    @classmethod
    def from_datetime(cls, dt: datetime) -> "DNP3Timestamp":
        """Create from Python datetime.

        Args:
            dt: datetime object (should be timezone-aware, preferably UTC).

        Returns:
            DNP3Timestamp instance.
        """
        # Convert to UTC timestamp
        timestamp = dt.timestamp()
        ms = int(timestamp * _MS_PER_SECOND)
        return cls(ms)

    @classmethod
    def now(cls) -> "DNP3Timestamp":
        """Create timestamp for current time.

        Returns:
            DNP3Timestamp for current UTC time.
        """
        return cls.from_datetime(datetime.now(UTC))

    def to_bytes(self) -> bytes:
        """Serialize to 6 bytes (little-endian).

        Returns:
            6-byte representation of the timestamp.
        """
        return self.milliseconds.to_bytes(TIMESTAMP_SIZE, byteorder="little")

    @classmethod
    def from_bytes(cls, data: bytes) -> "DNP3Timestamp":
        """Parse from 6 bytes (little-endian).

        Args:
            data: 6-byte timestamp data.

        Returns:
            DNP3Timestamp instance.

        Raises:
            ValueError: If data is not exactly 6 bytes.
        """
        if len(data) != TIMESTAMP_SIZE:
            msg = f"Expected {TIMESTAMP_SIZE} bytes, got {len(data)}"
            raise ValueError(msg)
        ms = int.from_bytes(data, byteorder="little")
        return cls(ms)
