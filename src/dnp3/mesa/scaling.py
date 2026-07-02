"""Engineering-to-transmission value scaling for the MESA PICS profile.

The DNP3 wire carries the transmission integer, never the engineering float.
A point's ``multiplier`` and ``offset`` are profile metadata and are never
transmitted; they define the affine map between the two representations:

    engineering = transmission * multiplier + offset
    transmission = round((engineering - offset) / multiplier)

This module reproduces mesa-tool's ``TransmissionI32::try_from_engineering``
(``backend/src/common/src/profile/values.rs``) so the two sides agree bit for
bit. The rounding rule matters: mesa-tool rounds the raw quotient half away
from zero when the fractional part exceeds 1e-7, and truncates toward zero
otherwise. Python's built-in :func:`round` is banker's rounding, so it cannot
be used here; :func:`_round_half_away_from_zero` implements the correct rule.
"""

from __future__ import annotations

import math

__all__ = [
    "I32_MAX",
    "I32_MIN",
    "ScalingError",
    "engineering_to_transmission",
    "transmission_to_engineering",
]

# Signed 32-bit range. AI/AO transmission integers are signed and bounded by
# these limits; a raw quotient outside this range cannot be transmitted.
I32_MIN = -2_147_483_648
I32_MAX = 2_147_483_647

# Fractional part below this magnitude is treated as an exact integer and
# truncated toward zero; above it, the value is rounded half away from zero.
# Matches mesa-tool's 1e-7 threshold in values.rs.
_FRACTION_THRESHOLD = 1e-7


class ScalingError(ValueError):
    """Raised when an engineering value cannot be scaled to a transmission int.

    Covers a non-finite engineering value (NaN, inf), a zero or non-finite
    multiplier, a non-finite offset, and a raw quotient outside the signed
    32-bit range.
    """


def _round_half_away_from_zero(raw: float) -> int:
    """Round *raw* to the nearest integer, breaking ties away from zero.

    ``round(2.5)`` is 3 and ``round(-2.5)`` is -3, unlike Python's built-in
    :func:`round`, which rounds half to even. This matches Rust's ``f64::round``
    that mesa-tool uses, so the two implementations produce identical wire
    integers.
    """
    return math.floor(raw + 0.5) if raw >= 0 else math.ceil(raw - 0.5)


def engineering_to_transmission(
    engineering_value: float,
    multiplier: float,
    offset: float,
) -> int:
    """Convert an engineering-unit value to the signed transmission integer.

    Args:
        engineering_value: The value in engineering units (the profile's
            ``value`` field for an AI point).
        multiplier: The point's scaling multiplier. Must be non-zero and finite.
        offset: The point's scaling offset. Must be finite.

    Returns:
        The signed 32-bit transmission integer placed on the DNP3 wire.

    Raises:
        ScalingError: If *engineering_value* is non-finite (NaN, inf), if
            *multiplier* is zero or non-finite, if *offset* is non-finite,
            or if the raw quotient falls outside the signed 32-bit range.
    """
    if not math.isfinite(engineering_value):
        msg = f"engineering_value must be finite, got {engineering_value}"
        raise ScalingError(msg)
    if multiplier == 0.0:
        msg = f"multiplier cannot be zero (engineering_value={engineering_value})"
        raise ScalingError(msg)
    if not math.isfinite(multiplier):
        msg = f"multiplier must be finite, got {multiplier}"
        raise ScalingError(msg)
    if not math.isfinite(offset):
        msg = f"offset must be finite, got {offset}"
        raise ScalingError(msg)

    raw = (engineering_value - offset) / multiplier

    if raw < I32_MIN or raw > I32_MAX:
        msg = (
            f"scaled value out of signed 32-bit range: "
            f"raw={raw} (engineering_value={engineering_value}, "
            f"multiplier={multiplier}, offset={offset})"
        )
        raise ScalingError(msg)

    if abs(raw - math.trunc(raw)) > _FRACTION_THRESHOLD:
        return _round_half_away_from_zero(raw)
    return math.trunc(raw)


def transmission_to_engineering(
    transmission_value: int,
    multiplier: float,
    offset: float,
) -> float:
    """Convert a transmission integer back to its engineering-unit value.

    This is the inverse a master applies to interpret a read. The outstation
    stores the transmission integer, so this is used for readback assertions
    and round-trip checks, not on the outstation write path.
    """
    return transmission_value * multiplier + offset
