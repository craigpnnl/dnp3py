"""CRC-16/DNP implementation per IEEE 1815-2012 Annex E.

CRC parameters:
- Polynomial: 0x3D65
- Init: 0x0000
- RefIn: True (reflect input bytes)
- RefOut: True (reflect output)
- XorOut: 0xFFFF
- Check: 0x82EA (for "123456789")
"""

from functools import reduce


def _generate_crc_table() -> tuple[int, ...]:
    """Generate CRC lookup table for reflected polynomial."""
    # Reflected polynomial: 0x3D65 reflected = 0xA6BC
    poly = 0xA6BC
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)
    return tuple(table)


# Pre-computed CRC lookup table for reflected polynomial 0xA6BC (0x3D65 reflected)
_CRC_TABLE: tuple[int, ...] = _generate_crc_table()


def _update_crc(crc: int, byte: int) -> int:
    """Update CRC with a single byte using table lookup."""
    return (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]


def compute_crc(data: bytes) -> int:
    """Compute CRC-16/DNP for data.

    Args:
        data: Input bytes to compute CRC for.

    Returns:
        16-bit CRC value.
    """
    # Init = 0x0000, then XorOut = 0xFFFF
    crc = reduce(_update_crc, data, 0x0000)
    return crc ^ 0xFFFF


def verify_crc(data: bytes, expected: int) -> bool:
    """Verify CRC matches expected value.

    Args:
        data: Input bytes.
        expected: Expected 16-bit CRC value.

    Returns:
        True if CRC matches, False otherwise.
    """
    return compute_crc(data) == expected


def append_crc(data: bytes) -> bytes:
    """Append CRC to data in little-endian format.

    Args:
        data: Input bytes.

    Returns:
        Data with 2-byte CRC appended (little-endian).
    """
    crc = compute_crc(data)
    return data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
