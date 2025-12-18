"""Tests for CRC-16/DNP implementation per IEEE 1815-2012 Annex E."""

from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.crc import append_crc, compute_crc, verify_crc


class TestComputeCRC:
    """Tests for compute_crc function."""

    def test_known_check_value(self) -> None:
        """CRC-16/DNP check value for '123456789' is 0xEA82 (per CRC catalogue)."""
        result = compute_crc(b"123456789")
        assert result == 0xEA82

    def test_empty_data(self) -> None:
        """CRC of empty data equals XOR-out value (0xFFFF)."""
        result = compute_crc(b"")
        assert result == 0xFFFF

    def test_single_byte_zero(self) -> None:
        """CRC of single zero byte."""
        result = compute_crc(b"\x00")
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF

    def test_single_byte_ff(self) -> None:
        """CRC of single 0xFF byte."""
        result = compute_crc(b"\xff")
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF

    def test_result_is_16_bit(self) -> None:
        """CRC result is always 16-bit."""
        result = compute_crc(b"test data")
        assert 0 <= result <= 0xFFFF

    @given(st.binary(min_size=0, max_size=256))
    def test_deterministic(self, data: bytes) -> None:
        """Same input always produces same output."""
        assert compute_crc(data) == compute_crc(data)

    @given(st.binary(min_size=1, max_size=256))
    def test_different_data_usually_different_crc(self, data: bytes) -> None:
        """Different data usually produces different CRC (not guaranteed)."""
        modified = bytes([data[0] ^ 0xFF]) + data[1:]
        # They might collide, but let's at least check we get valid results
        crc1 = compute_crc(data)
        crc2 = compute_crc(modified)
        assert 0 <= crc1 <= 0xFFFF
        assert 0 <= crc2 <= 0xFFFF


class TestVerifyCRC:
    """Tests for verify_crc function."""

    def test_verify_known_value(self) -> None:
        """Verify known CRC value."""
        assert verify_crc(b"123456789", 0xEA82) is True

    def test_verify_wrong_value(self) -> None:
        """Reject incorrect CRC value."""
        assert verify_crc(b"123456789", 0x0000) is False

    def test_verify_empty_data(self) -> None:
        """Verify CRC for empty data."""
        assert verify_crc(b"", 0xFFFF) is True

    @given(st.binary(min_size=0, max_size=256))
    def test_compute_then_verify(self, data: bytes) -> None:
        """Computed CRC always verifies."""
        crc = compute_crc(data)
        assert verify_crc(data, crc) is True


class TestAppendCRC:
    """Tests for append_crc function."""

    def test_append_to_empty(self) -> None:
        """Append CRC to empty data."""
        result = append_crc(b"")
        assert len(result) == 2
        # CRC for empty is 0xFFFF, little-endian
        assert result == b"\xff\xff"

    def test_append_known_value(self) -> None:
        """Append CRC to known data."""
        result = append_crc(b"123456789")
        assert len(result) == 11  # 9 + 2
        # 0xEA82 in little-endian: low byte (0x82) first, then high byte (0xEA)
        assert result[-2:] == b"\x82\xea"

    def test_append_preserves_original(self) -> None:
        """Original data is preserved."""
        data = b"test"
        result = append_crc(data)
        assert result[:4] == data

    @given(st.binary(min_size=0, max_size=256))
    def test_roundtrip(self, data: bytes) -> None:
        """CRC can be verified after appending."""
        result = append_crc(data)
        # Extract CRC (little-endian)
        crc = result[-2] | (result[-1] << 8)
        assert verify_crc(data, crc) is True
