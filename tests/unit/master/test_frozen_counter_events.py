"""Value-asserting tests for group 23 (frozen counter events), IEEE 1815-2012 A.13.

Every variation (v1-v8) is delivered through ``Master.process_response`` to
``on_frozen_counter``, exactly as g20/g21/g22 already are. The wire bytes and
expected values are built by hand from the A.13 formal structures, never
produced by this library's own encoders. Regression cover for
craigpnnl/dnp3py#74.
"""

from datetime import UTC, datetime, timedelta

from dnp3.master.handler import CounterValue, DefaultSOEHandler
from dnp3.master.master import Master

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# 1-byte start/stop qualifier, range 0..0: a single object at index 0.
_QUAL_1BYTE_RANGE = bytes([0x00, 0x00, 0x00])


def _header(group: int, variation: int) -> bytes:
    return bytes([group, variation]) + _QUAL_1BYTE_RANGE


# A.13.x: DNP3TIME is a UINT48 count of milliseconds since the epoch,
# little-endian (11.3.4). Non-zero and non-round so a decoder reading the
# wrong slice of the object would not coincidentally match.
_TIME_MS = 1_700_000_000_321
_TIME_OCTETS = _TIME_MS.to_bytes(6, "little")
_EXPECTED_TIME = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=_TIME_MS)


def _deliver(body: bytes) -> DefaultSOEHandler:
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    info = master.process_response(RESPONSE_HEADER + body)
    assert info is not None
    return handler


def _assert_only_frozen_counter(handler: DefaultSOEHandler, expected: CounterValue) -> None:
    assert handler.frozen_counters == {expected.index: expected}
    assert handler.binary_inputs == {}
    assert handler.binary_outputs == {}
    assert handler.analog_inputs == {}
    assert handler.analog_outputs == {}
    assert handler.counters == {}


class TestFrozenCounterEventVariations:
    """One block per A.13 variation, decoded values asserted exactly."""

    def test_g23v1_32bit_with_flag_no_time(self) -> None:
        # A.13.1.2.2: BSTR8 flag, UINT32 count value, no time field.
        body = _header(23, 1) + bytes([0x21]) + (0x87654321).to_bytes(4, "little")
        handler = _deliver(body)
        _assert_only_frozen_counter(handler, CounterValue(index=0, value=0x87654321, quality=0x21, timestamp=None))

    def test_g23v2_16bit_with_flag_no_time(self) -> None:
        # A.13.2.2.2: BSTR8 flag, UINT16 count value, no time field.
        body = _header(23, 2) + bytes([0x03]) + (0x8765).to_bytes(2, "little")
        handler = _deliver(body)
        _assert_only_frozen_counter(handler, CounterValue(index=0, value=0x8765, quality=0x03, timestamp=None))

    def test_g23v3_32bit_with_flag_delta_no_time(self) -> None:
        # A.13.3.2.2: identical wire shape to v1; the delta semantics are not
        # wire-visible (A.13.3.2.3: obsolete, described for reference only).
        body = _header(23, 3) + bytes([0x11]) + (0x11223344).to_bytes(4, "little")
        handler = _deliver(body)
        _assert_only_frozen_counter(handler, CounterValue(index=0, value=0x11223344, quality=0x11, timestamp=None))

    def test_g23v4_16bit_with_flag_delta_no_time(self) -> None:
        # A.13.4.2.2: identical wire shape to v2.
        body = _header(23, 4) + bytes([0x05]) + (0x99AA).to_bytes(2, "little")
        handler = _deliver(body)
        _assert_only_frozen_counter(handler, CounterValue(index=0, value=0x99AA, quality=0x05, timestamp=None))

    def test_g23v5_32bit_with_flag_and_time(self) -> None:
        # A.13.5.2.2: BSTR8 flag, UINT32 count value, DNP3TIME.
        body = _header(23, 5) + bytes([0x21]) + (0x12345678).to_bytes(4, "little") + _TIME_OCTETS
        handler = _deliver(body)
        _assert_only_frozen_counter(
            handler, CounterValue(index=0, value=0x12345678, quality=0x21, timestamp=_EXPECTED_TIME)
        )

    def test_g23v6_16bit_with_flag_and_time(self) -> None:
        # A.13.6.2.2: BSTR8 flag, UINT16 count value, DNP3TIME.
        body = _header(23, 6) + bytes([0x61]) + (0x1234).to_bytes(2, "little") + _TIME_OCTETS
        handler = _deliver(body)
        _assert_only_frozen_counter(
            handler, CounterValue(index=0, value=0x1234, quality=0x61, timestamp=_EXPECTED_TIME)
        )

    def test_g23v7_32bit_with_flag_and_time_delta(self) -> None:
        # A.13.7.2.2: identical wire shape to v5 (A.13.7.2.3: obsolete).
        body = _header(23, 7) + bytes([0x09]) + (0x0A0B0C0D).to_bytes(4, "little") + _TIME_OCTETS
        handler = _deliver(body)
        _assert_only_frozen_counter(
            handler, CounterValue(index=0, value=0x0A0B0C0D, quality=0x09, timestamp=_EXPECTED_TIME)
        )

    def test_g23v8_16bit_with_flag_and_time_delta(self) -> None:
        # A.13.8.2.2: identical wire shape to v6 (A.13.8.2.3: obsolete).
        body = _header(23, 8) + bytes([0x0D]) + (0x0BCD).to_bytes(2, "little") + _TIME_OCTETS
        handler = _deliver(body)
        _assert_only_frozen_counter(
            handler, CounterValue(index=0, value=0x0BCD, quality=0x0D, timestamp=_EXPECTED_TIME)
        )


class TestFrozenCounterBlockAheadOfAnalogBlock:
    """A g23 block does not absorb the block that follows it."""

    def test_g23v5_block_and_g30v1_block_both_delivered(self) -> None:
        g23_block = _header(23, 5) + bytes([0x21]) + (0x12345678).to_bytes(4, "little") + _TIME_OCTETS
        # A.14.1: flag, INT32. Value 2401 fits in a positive INT32.
        g30_block = _header(30, 1) + bytes([0x01]) + (2401).to_bytes(4, "little", signed=True)

        handler = _deliver(g23_block + g30_block)

        assert handler.frozen_counters == {
            0: CounterValue(index=0, value=0x12345678, quality=0x21, timestamp=_EXPECTED_TIME)
        }
        assert handler.analog_inputs[0].value == 2401.0
        assert handler.analog_inputs[0].quality == 0x01


class TestGroup23TwoObjectsWithIndexPrefix:
    """Qualifier 0x17: 1-byte count, 1-byte index prefix per object (A.13.5.2.2).

    The first object's value has the top bit set (0x80000001): a decoder that
    reads the UINT32 count as signed misreads it as negative and fails this
    test on its own, without a separate mutation run.
    """

    def test_g23v5_two_objects_uint8_count_uint8_index(self) -> None:
        data = (
            bytes([23, 5, 0x17])
            + bytes([2])
            + bytes([12])
            + bytes([0x21])
            + (0x80000001).to_bytes(4, "little")
            + _TIME_OCTETS
            + bytes([200])
            + bytes([0x03])
            + (0x12345678).to_bytes(4, "little")
            + _TIME_OCTETS
        )
        handler = _deliver(data)
        assert handler.frozen_counters == {
            12: CounterValue(index=12, value=0x80000001, quality=0x21, timestamp=_EXPECTED_TIME),
            200: CounterValue(index=200, value=0x12345678, quality=0x03, timestamp=_EXPECTED_TIME),
        }
