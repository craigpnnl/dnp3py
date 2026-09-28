"""Value-asserting tests for the counter and frozen-counter variations craigpnnl/dnp3py#80
added to groups 20, 21 and 22: the with-flag delta, with-flag-and-time delta, and
without-flag (plain and delta) variations that groups 20 and 22 define per A.10 and A.12,
and every remaining group 21 variation per A.11, including g21v9.

Every object is built by hand from its Annex A formal structure; nothing is produced by
this library's own encoder. Each is delivered through `Master.process_response` on a full
response fragment, the same public entry point an outstation reply reaches.
"""

import struct
from datetime import UTC, datetime, timedelta

from dnp3.master.handler import CounterValue, ResponseInfo, SOEHandler
from dnp3.master.master import QUALITY_ONLINE, Master

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# DNP3TIME (11.3.4): UINT48 ms since the epoch, little-endian. Non-palindromic so a
# wrong stride or a wrong byte order both misread it.
_TIME_MS = 1_700_000_000_123
_TIME_OCTETS = _TIME_MS.to_bytes(6, "little")
_EXPECTED_TIME = _EPOCH + timedelta(milliseconds=_TIME_MS)


def _block(group: int, variation: int, index: int, data: bytes) -> bytes:
    """A one-object start-stop block (qualifier 0x00): group, variation, start, stop, data."""
    return bytes([group, variation, 0x00, index, index]) + data


class CountingHandler(SOEHandler):
    """Records every counter and frozen-counter value delivered, in call order."""

    def __init__(self) -> None:
        self.counters: list[CounterValue] = []
        self.frozen_counters: list[CounterValue] = []

    def on_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.counters.extend(values)

    def on_frozen_counter(self, values: list[CounterValue], info: ResponseInfo) -> None:
        self.frozen_counters.extend(values)


def _deliver(body: bytes) -> CountingHandler:
    handler = CountingHandler()
    Master(handler=handler).process_response(RESPONSE_HEADER + body)
    return handler


class TestGroup20Delta:
    """A.10.3, A.10.4, A.10.7, A.10.8: delta variations share their non-delta sibling's
    wire shape (flag, delta, and plain report the same fields; only the semantic meaning
    of the count differs). Obsolete per the standard; still on the wire, so still decoded.
    """

    def test_g20v3_32bit_with_flag_delta(self) -> None:
        # A.10.3.2.2: BSTR8 flag, UINT32 count.
        handler = _deliver(_block(20, 3, 7, bytes([0x21]) + struct.pack("<I", 0x12345678)))
        assert handler.counters == [CounterValue(index=7, value=0x12345678, quality=0x21)]

    def test_g20v4_16bit_with_flag_delta(self) -> None:
        # A.10.4.2.2: BSTR8 flag, UINT16 count.
        handler = _deliver(_block(20, 4, 3, bytes([0x03]) + struct.pack("<H", 0x1234)))
        assert handler.counters == [CounterValue(index=3, value=0x1234, quality=0x03)]

    def test_g20v7_32bit_without_flag_delta(self) -> None:
        # A.10.7.2.2: UINT32 count, no flag octet; quality defaults to online (0).
        handler = _deliver(_block(20, 7, 0, struct.pack("<I", 0x89ABCDEF)))
        assert handler.counters == [CounterValue(index=0, value=0x89ABCDEF, quality=QUALITY_ONLINE)]

    def test_g20v8_16bit_without_flag_delta(self) -> None:
        # A.10.8.2.2: UINT16 count, no flag octet.
        handler = _deliver(_block(20, 8, 0, struct.pack("<H", 0xABCD)))
        assert handler.counters == [CounterValue(index=0, value=0xABCD, quality=QUALITY_ONLINE)]


class TestGroup21RemainingVariations:
    """A.11.3, A.11.4, A.11.7 to A.11.12: every g21 variation not already registered
    by craigpnnl/dnp3py#79 (v1, v2, v5, v6).
    """

    def test_g21v3_32bit_with_flag_delta(self) -> None:
        # A.11.3.2.2: BSTR8 flag, UINT32 count.
        handler = _deliver(_block(21, 3, 4, bytes([0x21]) + struct.pack("<I", 0x12345678)))
        assert handler.frozen_counters == [CounterValue(index=4, value=0x12345678, quality=0x21)]

    def test_g21v4_16bit_with_flag_delta(self) -> None:
        # A.11.4.2.2: BSTR8 flag, UINT16 count.
        handler = _deliver(_block(21, 4, 2, bytes([0x03]) + struct.pack("<H", 0x1234)))
        assert handler.frozen_counters == [CounterValue(index=2, value=0x1234, quality=0x03)]

    def test_g21v7_32bit_with_flag_and_time_delta(self) -> None:
        # A.11.7.2.2: BSTR8 flag, UINT32 count, DNP3TIME.
        handler = _deliver(_block(21, 7, 1, bytes([0x21]) + struct.pack("<I", 0x12345678) + _TIME_OCTETS))
        assert handler.frozen_counters == [
            CounterValue(index=1, value=0x12345678, quality=0x21, timestamp=_EXPECTED_TIME)
        ]

    def test_g21v8_16bit_with_flag_and_time_delta(self) -> None:
        # A.11.8.2.2: BSTR8 flag, UINT16 count, DNP3TIME.
        handler = _deliver(_block(21, 8, 1, bytes([0x21]) + struct.pack("<H", 0x1234) + _TIME_OCTETS))
        assert handler.frozen_counters == [CounterValue(index=1, value=0x1234, quality=0x21, timestamp=_EXPECTED_TIME)]

    def test_g21v9_32bit_without_flag(self) -> None:
        # A.11.9.2.2: UINT32 count, no flag octet. Required by IEEE 1815.2-2025 Table 7.
        handler = _deliver(_block(21, 9, 0, struct.pack("<I", 0x89ABCDEF)))
        assert handler.frozen_counters == [CounterValue(index=0, value=0x89ABCDEF, quality=QUALITY_ONLINE)]

    def test_g21v10_16bit_without_flag(self) -> None:
        # A.11.10.2.2: UINT16 count, no flag octet.
        handler = _deliver(_block(21, 10, 0, struct.pack("<H", 0xABCD)))
        assert handler.frozen_counters == [CounterValue(index=0, value=0xABCD, quality=QUALITY_ONLINE)]

    def test_g21v11_32bit_without_flag_delta(self) -> None:
        # A.11.11.2.2: UINT32 count, no flag octet.
        handler = _deliver(_block(21, 11, 0, struct.pack("<I", 0x89ABCDEF)))
        assert handler.frozen_counters == [CounterValue(index=0, value=0x89ABCDEF, quality=QUALITY_ONLINE)]

    def test_g21v12_16bit_without_flag_delta(self) -> None:
        # A.11.12.2.2: UINT16 count, no flag octet.
        handler = _deliver(_block(21, 12, 0, struct.pack("<H", 0xABCD)))
        assert handler.frozen_counters == [CounterValue(index=0, value=0xABCD, quality=QUALITY_ONLINE)]

    def test_g21v9_block_ahead_of_g30v1_block_both_delivered(self) -> None:
        """A g21v9 block followed by a g30v1 block delivers both: the new row must give
        the parser a real width, or the g21v9 block absorbs the g30v1 bytes behind it.
        """
        body = (
            _block(21, 9, 0, struct.pack("<I", 0x89ABCDEF)) + bytes([30, 1, 0x00, 0, 0, 0x01]) + struct.pack("<i", 2401)
        )
        handler = _deliver(body)
        assert handler.frozen_counters == [CounterValue(index=0, value=0x89ABCDEF, quality=QUALITY_ONLINE)]


class TestGroup22Delta:
    """A.12.3, A.12.4, A.12.7, A.12.8: counter-event delta variations, same shape as
    their non-delta siblings (v1, v2, v5, v6).
    """

    def test_g22v3_32bit_with_flag_delta(self) -> None:
        # A.12.3.2.2: BSTR8 flag, UINT32 count.
        handler = _deliver(_block(22, 3, 5, bytes([0x21]) + struct.pack("<I", 0x12345678)))
        assert handler.counters == [CounterValue(index=5, value=0x12345678, quality=0x21)]

    def test_g22v4_16bit_with_flag_delta(self) -> None:
        # A.12.4.2.2: BSTR8 flag, UINT16 count.
        handler = _deliver(_block(22, 4, 6, bytes([0x03]) + struct.pack("<H", 0x1234)))
        assert handler.counters == [CounterValue(index=6, value=0x1234, quality=0x03)]

    def test_g22v7_32bit_with_flag_and_time_delta(self) -> None:
        # A.12.7.2.2: BSTR8 flag, UINT32 count, DNP3TIME.
        handler = _deliver(_block(22, 7, 1, bytes([0x21]) + struct.pack("<I", 0x12345678) + _TIME_OCTETS))
        assert handler.counters == [CounterValue(index=1, value=0x12345678, quality=0x21, timestamp=_EXPECTED_TIME)]

    def test_g22v8_16bit_with_flag_and_time_delta(self) -> None:
        # A.12.8.2.2: BSTR8 flag, UINT16 count, DNP3TIME.
        handler = _deliver(_block(22, 8, 1, bytes([0x21]) + struct.pack("<H", 0x1234) + _TIME_OCTETS))
        assert handler.counters == [CounterValue(index=1, value=0x1234, quality=0x21, timestamp=_EXPECTED_TIME)]
