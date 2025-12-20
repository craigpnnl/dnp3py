"""Tests for DNP3 timestamp handling."""

from datetime import UTC, datetime

from dnp3.core.timestamp import DNP3Timestamp


class TestDNP3Timestamp:
    """Tests for DNP3Timestamp."""

    def test_from_milliseconds(self) -> None:
        """Create timestamp from milliseconds since epoch."""
        ts = DNP3Timestamp(1000)
        assert ts.milliseconds == 1000

    def test_zero_timestamp(self) -> None:
        """Zero milliseconds is valid (epoch)."""
        ts = DNP3Timestamp(0)
        assert ts.milliseconds == 0

    def test_to_datetime(self) -> None:
        """Convert to Python datetime."""
        # 2020-01-01 00:00:00 UTC in milliseconds
        ms = 1577836800000
        ts = DNP3Timestamp(ms)
        dt = ts.to_datetime()
        assert dt.year == 2020
        assert dt.month == 1
        assert dt.day == 1
        assert dt.hour == 0
        assert dt.minute == 0
        assert dt.second == 0
        assert dt.tzinfo == UTC

    def test_from_datetime(self) -> None:
        """Create timestamp from Python datetime."""
        dt = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
        ts = DNP3Timestamp.from_datetime(dt)
        assert ts.milliseconds == 1577836800000

    def test_from_datetime_with_microseconds(self) -> None:
        """Microseconds are truncated to milliseconds."""
        dt = datetime(2020, 1, 1, 0, 0, 0, 500000, tzinfo=UTC)
        ts = DNP3Timestamp.from_datetime(dt)
        # 500000 microseconds = 500 milliseconds
        assert ts.milliseconds == 1577836800500

    def test_now(self) -> None:
        """Create timestamp for current time."""
        ts = DNP3Timestamp.now()
        # Should be after year 2020
        assert ts.milliseconds > 1577836800000

    def test_to_bytes(self) -> None:
        """Serialize to 6 bytes (little-endian)."""
        ts = DNP3Timestamp(0x0102030405)
        data = ts.to_bytes()
        assert len(data) == 6
        assert data == b"\x05\x04\x03\x02\x01\x00"

    def test_from_bytes(self) -> None:
        """Parse from 6 bytes (little-endian)."""
        data = b"\x05\x04\x03\x02\x01\x00"
        ts = DNP3Timestamp.from_bytes(data)
        assert ts.milliseconds == 0x0102030405

    def test_roundtrip_bytes(self) -> None:
        """Roundtrip through bytes."""
        original = DNP3Timestamp(1577836800000)
        data = original.to_bytes()
        restored = DNP3Timestamp.from_bytes(data)
        assert restored.milliseconds == original.milliseconds

    def test_equality(self) -> None:
        """Timestamps with same milliseconds are equal."""
        ts1 = DNP3Timestamp(1000)
        ts2 = DNP3Timestamp(1000)
        assert ts1 == ts2

    def test_inequality(self) -> None:
        """Timestamps with different milliseconds are not equal."""
        ts1 = DNP3Timestamp(1000)
        ts2 = DNP3Timestamp(2000)
        assert ts1 != ts2

    def test_max_48_bit_value(self) -> None:
        """Maximum 48-bit timestamp value."""
        max_ms = (1 << 48) - 1  # 0xFFFFFFFFFFFF
        ts = DNP3Timestamp(max_ms)
        assert ts.milliseconds == max_ms
        data = ts.to_bytes()
        assert data == b"\xff\xff\xff\xff\xff\xff"
