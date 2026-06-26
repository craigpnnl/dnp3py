"""Tests for DIRECT_OPERATE response byte-level format correctness.

Validates that the outstation echoes control command responses with the
correct qualifier-aware byte widths for count and index prefix fields.

The Rust dnp3 crate v1.6 uses qualifier 0x28 (2-byte count, 2-byte index
prefix) for control operations. The outstation must match the request's
qualifier exactly in the response.

Ref: IEEE 1815-2012 Clause 4, Object Header Qualifiers.
"""

from __future__ import annotations

import struct

from dnp3.database import Database
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import Outstation


def _make_outstation() -> Outstation:
    """Create an outstation with BO0 and AO0 configured."""
    db = Database()
    db.add_binary_output(0)
    db.add_analog_input(0)
    return Outstation(database=db, config=OutstationConfig())


def _build_crob_request(qualifier: int, index: int) -> bytes:
    """Build a DIRECT_OPERATE request for Group 12 Var 1.

    Args:
        qualifier: Qualifier byte (e.g. 0x17 or 0x28).
        index: Point index for the CROB.

    Returns:
        Raw request bytes.
    """
    # CROB payload: control(1) + count(1) + on_time(4) + off_time(4) + status(1) = 11
    crob = struct.pack("<BB", 0x03, 1) + struct.pack("<II", 0, 0) + struct.pack("<B", 0)

    header = bytes([0xC0, 0x05, 12, 1, qualifier])

    if qualifier == 0x17:
        # 1-byte count, 1-byte index prefix
        header += bytes([1, index & 0xFF])
    elif qualifier == 0x28:
        # 2-byte count, 2-byte index prefix
        header += struct.pack("<H", 1) + struct.pack("<H", index)
    else:
        raise ValueError(f"Unsupported qualifier 0x{qualifier:02x}")

    return header + crob


def _build_ao_request(qualifier: int, variation: int, index: int, value_bytes: bytes) -> bytes:
    """Build a DIRECT_OPERATE request for Group 41.

    Args:
        qualifier: Qualifier byte.
        variation: AO variation (1-4).
        index: Point index.
        value_bytes: Encoded value bytes.

    Returns:
        Raw request bytes.
    """
    header = bytes([0xC0, 0x05, 41, variation, qualifier])

    if qualifier == 0x17:
        header += bytes([1, index & 0xFF])
    elif qualifier == 0x28:
        header += struct.pack("<H", 1) + struct.pack("<H", index)
    else:
        raise ValueError(f"Unsupported qualifier 0x{qualifier:02x}")

    # value + status byte (0)
    return header + value_bytes + bytes([0])


class TestCROBResponseFormat:
    """Verify CROB (g12v1) DIRECT_OPERATE response byte layout."""

    def test_qualifier_0x17_response_length(self) -> None:
        """Response with 1-byte qualifier is 20 bytes."""
        outstation = _make_outstation()
        request = _build_crob_request(0x17, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # 4(hdr) + 3(obj) + 1(count) + 1(index) + 11(crob) = 20
        assert len(resp) == 20

    def test_qualifier_0x17_echoes_qualifier(self) -> None:
        """Response preserves qualifier 0x17 from request."""
        outstation = _make_outstation()
        request = _build_crob_request(0x17, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        assert resp[6] == 0x17

    def test_qualifier_0x28_response_length(self) -> None:
        """Response with 2-byte qualifier is 22 bytes."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # 4(hdr) + 3(obj) + 2(count) + 2(index) + 11(crob) = 22
        assert len(resp) == 22

    def test_qualifier_0x28_echoes_qualifier(self) -> None:
        """Response preserves qualifier 0x28 from request."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        assert resp[6] == 0x28

    def test_qualifier_0x28_count_is_2_bytes(self) -> None:
        """Count field uses 2 bytes for qualifier 0x28."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        count = int.from_bytes(resp[7:9], "little")
        assert count == 1

    def test_qualifier_0x28_index_is_2_bytes(self) -> None:
        """Index prefix uses 2 bytes for qualifier 0x28."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        index = int.from_bytes(resp[9:11], "little")
        assert index == 0

    def test_qualifier_0x28_crob_fields_intact(self) -> None:
        """CROB fields are correctly echoed after 2-byte index."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # CROB starts at byte 11 for 0x28
        assert resp[11] == 0x03  # control code (LATCH_ON)
        assert resp[12] == 1  # op count

    def test_qualifier_0x28_status_at_correct_offset(self) -> None:
        """Status byte is at the end of the CROB (byte 21 for 0x28)."""
        outstation = _make_outstation()
        request = _build_crob_request(0x28, index=0)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # Status is the last byte of the CROB object
        # 4(hdr) + 3(obj) + 2(count) + 2(index) + 10(crob fields) + 1(status) = 22
        # Status at byte 21
        status = resp[21]
        # Should be a valid CommandStatus value
        assert status in range(128)


class TestAOResponseFormat:
    """Verify Analog Output (g41) DIRECT_OPERATE response byte layout."""

    def test_ao_var1_qualifier_0x28_response_length(self) -> None:
        """AO var1 (int32) response with 0x28 qualifier is 16 bytes."""
        outstation = _make_outstation()
        value = struct.pack("<i", 42)
        request = _build_ao_request(0x28, variation=1, index=0, value_bytes=value)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # 4(hdr) + 3(obj) + 2(count) + 2(index) + 4(value) + 1(status) = 16
        assert len(resp) == 16

    def test_ao_var3_qualifier_0x28_response_length(self) -> None:
        """AO var3 (float32) response with 0x28 qualifier is 16 bytes."""
        outstation = _make_outstation()
        value = struct.pack("<f", 3.14)
        request = _build_ao_request(0x28, variation=3, index=0, value_bytes=value)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # 4(hdr) + 3(obj) + 2(count) + 2(index) + 4(value) + 1(status) = 16
        assert len(resp) == 16

    def test_ao_var1_qualifier_0x17_response_length(self) -> None:
        """AO var1 (int32) response with 0x17 qualifier is 14 bytes."""
        outstation = _make_outstation()
        value = struct.pack("<i", 42)
        request = _build_ao_request(0x17, variation=1, index=0, value_bytes=value)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # 4(hdr) + 3(obj) + 1(count) + 1(index) + 4(value) + 1(status) = 14
        assert len(resp) == 14

    def test_ao_qualifier_0x28_echoes_value(self) -> None:
        """AO response echoes the value bytes from the request."""
        outstation = _make_outstation()
        value = struct.pack("<i", 42)
        request = _build_ao_request(0x28, variation=1, index=0, value_bytes=value)
        responses = outstation.process_request(request)
        resp = responses[0].to_bytes()
        # Value starts at byte 11 (after 4+3+2+2)
        echoed_value = struct.unpack("<i", resp[11:15])[0]
        assert echoed_value == 42
