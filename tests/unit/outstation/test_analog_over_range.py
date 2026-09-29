"""Tests for #159: an out-of-range analog input is reported at its limit.

IEEE 1815-2012 11.6.1.1 rules 2 and 3 (Note 4): a value outside a 32-bit
variation's range is reported as the nearer limit with OVER_RANGE set,
rather than raised. Before this fix, the static (g30v1) and event (g32v1)
analog input encoders narrowed with a bare int(), which raised for any
value outside the 32-bit signed range and for infinity, failing the whole
response (issue #159).

Neither IEEE 1815-2012 nor IEEE 1815.2-2025 states a reporting rule for
NaN (searched: 0 hits for "OVER_RANGE" or "NaN" in the 1815.2-2025 text).
TestNaNBehaviorAtBase pins the current (unchanged) behavior rather than
choosing one.
"""

import math

import pytest

from dnp3.application.builder import build_class_poll, build_integrity_poll
from dnp3.application.fragment import ResponseFragment
from dnp3.core.flags import IIN, AnalogQuality
from dnp3.database import Database, EventClass
from dnp3.database.point import AnalogInputConfig
from dnp3.objects.analog_input import AnalogInput32, AnalogInputEvent32
from dnp3.outstation.outstation import Outstation

ONLINE = AnalogQuality.ONLINE
INT32_MAX = 2**31 - 1
INT32_MIN = -(2**31)


def _extract_object_data(responses: list[ResponseFragment], group: int, variation: int) -> bytes:
    """Return the raw data bytes from the first matching object block."""
    for frag in responses:
        for obj in frag.objects:
            if obj.header.group == group and obj.header.variation == variation:
                return bytes(obj.data)
    msg = f"No g{group}v{variation} block found in responses"
    raise AssertionError(msg)


def _static_ai(value: float, quality: AnalogQuality = ONLINE) -> bytes:
    """Run one analog input through an integrity poll and return its g30v1 object bytes."""
    db = Database()
    db.add_analog_input(0, value=value, quality=quality)
    outstation = Outstation(database=db)
    responses = outstation.process_request(build_integrity_poll().to_bytes())
    block_data = _extract_object_data(responses, group=30, variation=1)
    return block_data[2:]  # skip the 2-byte start/stop range header


def _event_ai(value: float, quality: AnalogQuality = ONLINE) -> bytes:
    """Update one analog input to `value` and return its g32v1 event object bytes."""
    db = Database()
    db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1, deadband=0))
    db.update_analog_input(0, value=value, quality=quality)
    outstation = Outstation(database=db)
    responses = outstation.process_request(build_class_poll(class_1=True, class_2=False, class_3=False).to_bytes())
    block_data = _extract_object_data(responses, group=32, variation=1)
    # qualifier 0x17: data[0]=count, data[1]=index, data[2:7]=object (5 bytes).
    return block_data[2:7]


class TestStaticOverRange:
    """g30v1 clamp and OVER_RANGE at the 32-bit signed limits and infinity."""

    def test_int32_max_is_in_range(self) -> None:
        assert _static_ai(float(INT32_MAX)) == AnalogInput32(quality=ONLINE, value=INT32_MAX).to_bytes()

    def test_above_int32_max_clamps_over_range(self) -> None:
        # 1e12 is the issue's reproduction value. Literal bytes, not AnalogInput32:
        # the SUT calls AnalogInput32 itself, so building expected from it would
        # only prove self-agreement.
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MAX.to_bytes(4, "little", signed=True)
        assert _static_ai(1e12) == expected

    def test_int32_min_is_in_range(self) -> None:
        assert _static_ai(float(INT32_MIN)) == AnalogInput32(quality=ONLINE, value=INT32_MIN).to_bytes()

    def test_below_int32_min_clamps_over_range(self) -> None:
        expected = AnalogInput32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MIN).to_bytes()
        assert _static_ai(-1e12) == expected

    def test_positive_infinity_clamps_over_range(self) -> None:
        expected = AnalogInput32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MAX).to_bytes()
        assert _static_ai(math.inf) == expected

    def test_negative_infinity_clamps_over_range(self) -> None:
        expected = AnalogInput32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MIN).to_bytes()
        assert _static_ai(-math.inf) == expected

    def test_in_range_value_byte_identical_to_base(self) -> None:
        """An in-range value's bytes are untouched by the clamp path (invariant)."""
        assert _static_ai(42.0) == bytes([int(ONLINE)]) + (42).to_bytes(4, "little", signed=True)

    def test_fractional_in_range_truncates_not_rounds(self) -> None:
        """int() truncation, not round(): 42.7 encodes as 42, never 43."""
        expected = bytes([int(ONLINE)]) + (42).to_bytes(4, "little", signed=True)
        assert _static_ai(42.7) == expected

    def test_negative_fractional_in_range_truncates_not_rounds(self) -> None:
        """Truncation toward zero, not round: -42.7 encodes as -42, never -43."""
        expected = bytes([int(ONLINE)]) + (-42).to_bytes(4, "little", signed=True)
        assert _static_ai(-42.7) == expected

    def test_half_above_int32_max_sets_over_range(self) -> None:
        """IEEE 1815-2012 11.6.1.1 rule 3 compares the true value, not a truncated one.

        2147483647.5 truncates to INT32_MAX, which is in range on its own,
        but the true value exceeds it: OVER_RANGE must still be set.
        """
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MAX.to_bytes(4, "little", signed=True)
        assert _static_ai(2147483647.5) == expected

    def test_int32_max_plus_one_clamps_over_range(self) -> None:
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MAX.to_bytes(4, "little", signed=True)
        assert _static_ai(float(INT32_MAX) + 1.0) == expected

    def test_int32_min_minus_one_clamps_over_range(self) -> None:
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MIN.to_bytes(4, "little", signed=True)
        assert _static_ai(float(INT32_MIN) - 1.0) == expected


class TestOverRangeBitPreservedInRange:
    """An OVER_RANGE bit already set on the point is kept for an in-range value.

    _clamp_int_range only ORs OVER_RANGE in; it never clears a bit the
    caller already set. Today's behavior is "kept", pinned here.
    """

    def test_preexisting_over_range_bit_survives_in_range_value(self) -> None:
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + (42).to_bytes(4, "little", signed=True)
        assert _static_ai(42.0, quality=ONLINE | AnalogQuality.OVER_RANGE) == expected


class TestEventOverRange:
    """g32v1 clamp and OVER_RANGE, mirroring the static case."""

    def test_int32_max_is_in_range(self) -> None:
        expected = bytes([int(ONLINE)]) + INT32_MAX.to_bytes(4, "little", signed=True)
        assert _event_ai(float(INT32_MAX)) == expected

    def test_int32_min_is_in_range(self) -> None:
        expected = bytes([int(ONLINE)]) + INT32_MIN.to_bytes(4, "little", signed=True)
        assert _event_ai(float(INT32_MIN)) == expected

    def test_above_int32_max_clamps_over_range(self) -> None:
        expected = AnalogInputEvent32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MAX).to_bytes()
        assert _event_ai(1e12) == expected

    def test_below_int32_min_clamps_over_range(self) -> None:
        expected = AnalogInputEvent32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MIN).to_bytes()
        assert _event_ai(-1e12) == expected

    def test_positive_infinity_clamps_over_range(self) -> None:
        expected = AnalogInputEvent32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MAX).to_bytes()
        assert _event_ai(math.inf) == expected

    def test_negative_infinity_clamps_over_range(self) -> None:
        expected = AnalogInputEvent32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MIN).to_bytes()
        assert _event_ai(-math.inf) == expected

    def test_in_range_value_byte_identical_to_base(self) -> None:
        assert _event_ai(-54321.0) == bytes([int(ONLINE)]) + (-54321).to_bytes(4, "little", signed=True)

    def test_fractional_in_range_truncates_not_rounds(self) -> None:
        expected = bytes([int(ONLINE)]) + (42).to_bytes(4, "little", signed=True)
        assert _event_ai(42.7) == expected

    def test_negative_fractional_in_range_truncates_not_rounds(self) -> None:
        expected = bytes([int(ONLINE)]) + (-42).to_bytes(4, "little", signed=True)
        assert _event_ai(-42.7) == expected

    def test_int32_max_plus_one_clamps_over_range(self) -> None:
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MAX.to_bytes(4, "little", signed=True)
        assert _event_ai(float(INT32_MAX) + 1.0) == expected

    def test_int32_min_minus_one_clamps_over_range(self) -> None:
        expected = bytes([int(ONLINE | AnalogQuality.OVER_RANGE)]) + INT32_MIN.to_bytes(4, "little", signed=True)
        assert _event_ai(float(INT32_MIN) - 1.0) == expected

    def test_comm_lost_quality_and_over_range_both_carried(self) -> None:
        """The event's own quality is carried through, not hardcoded to ONLINE.

        COMM_LOST (no ONLINE) plus an over-range value: the output must
        show both COMM_LOST and OVER_RANGE, proving the quality byte comes
        from the event rather than a fixed constant.
        """
        expected = bytes([int(AnalogQuality.COMM_LOST | AnalogQuality.OVER_RANGE)])
        expected += INT32_MAX.to_bytes(4, "little", signed=True)
        assert _event_ai(1e12, quality=AnalogQuality.COMM_LOST) == expected


class TestClassZeroPollWithOverRangePoints:
    """A Class 0 poll with over-range points among in-range ones answers every point (#159)."""

    def test_every_point_returned_with_its_own_bytes(self) -> None:
        db = Database()
        db.add_analog_input(0, value=1e12, quality=ONLINE)
        db.add_analog_input(1, value=-1e12, quality=ONLINE)
        db.add_analog_input(2, value=42.0, quality=ONLINE)
        outstation = Outstation(database=db)

        responses = outstation.process_request(build_integrity_poll().to_bytes())
        block_data = _extract_object_data(responses, group=30, variation=1)

        # start/stop range header (2 bytes, indices 0-2) + 3 * 5-byte g30v1 objects.
        assert block_data[0] == 0, "start index must be 0"
        assert block_data[1] == 2, "stop index must be 2"
        objects = block_data[2:]
        assert len(objects) == 15, f"expected 3 objects of 5 bytes, got {len(objects)} bytes"

        point0 = objects[0:5]
        point1 = objects[5:10]
        point2 = objects[10:15]

        assert point0 == AnalogInput32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MAX).to_bytes()
        assert point1 == AnalogInput32(quality=ONLINE | AnalogQuality.OVER_RANGE, value=INT32_MIN).to_bytes()
        assert point2 == AnalogInput32(quality=ONLINE, value=42).to_bytes(), (
            "an out-of-range point must not change a neighboring in-range point's bytes"
        )
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin


class TestNaNBehaviorAtBase:
    """NaN is not settled by either standard (searched both texts): behavior is left as at base.

    Base behavior: int(nan) raises ValueError inside the point serializer,
    process_request's handler-exception catch (outstation.py) turns that
    into a null response with IIN.PARAMETER_ERROR, exactly as it did before
    #159 for every out-of-range analog value. This pins that base behavior
    is unchanged for NaN specifically, while items 1/2 change it for every
    finite and infinite out-of-range value.
    """

    def test_static_nan_raises_and_is_answered_as_parameter_error(self) -> None:
        db = Database()
        db.add_analog_input(0, value=math.nan, quality=ONLINE)
        outstation = Outstation(database=db)

        responses = outstation.process_request(build_integrity_poll().to_bytes())

        assert len(responses) == 1
        assert IIN.PARAMETER_ERROR in responses[0].header.iin
        assert responses[0].objects == (), "no value may be synthesized for NaN"

    def test_event_nan_update_generates_no_event(self) -> None:
        """A NaN update never reaches the g32v1 serializer at all.

        AnalogInputPoint.update's deadband check is `abs(value -
        last_event_value) >= deadband`; abs(nan - x) is nan, and every
        comparison against nan is False, so the event is never queued.
        This guard lives in database/point.py, untouched by #159: unlike
        the static path, the event path's NaN behavior is "silently
        dropped", not "raises", and both are unchanged by this fix.
        """
        db = Database()
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1, deadband=0))
        changed = db.update_analog_input(0, value=math.nan, quality=ONLINE)
        assert changed is False, "a NaN update's deadband comparison (NaN >= 0) is always False"

        outstation = Outstation(database=db)
        responses = outstation.process_request(build_class_poll(class_1=True, class_2=False, class_3=False).to_bytes())

        assert len(responses) == 1
        assert responses[0].objects == (), "no event was queued, so none can be reported"
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin

    def test_int_of_nan_raises_valueerror(self) -> None:
        """Documents the mechanism: NaN fails both range comparisons and reaches int()."""
        with pytest.raises(ValueError, match="NaN"):
            int(math.nan)
