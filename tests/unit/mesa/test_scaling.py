"""Tests for the engineering-to-transmission scaling module.

These are the highest-risk data-invariant assertions in DNP-022: the DNP3 wire
carries the transmission integer, never the engineering float. A wrong direction,
a truncate where a round is required, or a missing guard writes a plausible but
wrong integer onto the wire that no non-crash test would catch. Every case here
asserts an exact transmission integer against a hand-computed value.
"""

from __future__ import annotations

import math

import pytest

from dnp3.mesa.scaling import (
    ScalingError,
    engineering_to_transmission,
    transmission_to_engineering,
)


class TestBasicScaling:
    """A representative multiplier != 1 / offset != 0 case."""

    def test_multiplier_offset_exact_integer(self) -> None:
        # raw = (engineering - offset) / multiplier = (120 - 0) / 0.1 = 1200
        assert engineering_to_transmission(120.0, multiplier=0.1, offset=0.0) == 1200

    def test_multiplier_and_nonzero_offset(self) -> None:
        # raw = (25.0 - 5.0) / 0.5 = 40
        assert engineering_to_transmission(25.0, multiplier=0.5, offset=5.0) == 40

    def test_identity_scaling(self) -> None:
        # multiplier 1, offset 0: transmission equals engineering
        assert engineering_to_transmission(1200.0, multiplier=1.0, offset=0.0) == 1200


class TestSignedAndNegative:
    """Transmission integers are signed; negative minima must round-trip."""

    def test_negative_engineering_value(self) -> None:
        # raw = (-500.0 - 0.0) / 0.1 = -5000
        assert engineering_to_transmission(-500.0, multiplier=0.1, offset=0.0) == -5000

    def test_negative_minimum_domain(self) -> None:
        # A point whose valid range spans negative transmission values.
        # eng = raw * mult + off; for raw -2147483648, mult 1, off 0 -> eng -2147483648
        raw = engineering_to_transmission(-2_147_483_648.0, multiplier=1.0, offset=0.0)
        assert raw == -2_147_483_648

    def test_power_factor_sign_preserved_leading_positive(self) -> None:
        # Power factor: leading positive, lagging negative. The sign must survive
        # scaling; do NOT map to the absolute value. multiplier 0.001, offset 0.
        # raw = (0.95 - 0) / 0.001 = 950
        assert engineering_to_transmission(0.95, multiplier=0.001, offset=0.0) == 950

    def test_power_factor_sign_preserved_lagging_negative(self) -> None:
        # raw = (-0.95 - 0) / 0.001 = -950. A sign flip here would be a
        # silent power-factor corruption (Vance Finding B).
        assert engineering_to_transmission(-0.95, multiplier=0.001, offset=0.0) == -950


class TestRoundVsTruncateBoundary:
    """The 1e-7 fractional threshold: below it truncate toward zero, above it
    round half away from zero. Python's built-in round() is banker's rounding
    and would give wrong results at the .5 boundary, so the implementation must
    round half away from zero to match mesa-tool bit for bit."""

    def test_fraction_below_threshold_truncates_toward_zero(self) -> None:
        # raw = 1200.00000005 -> fract 5e-8 < 1e-7 -> truncate to 1200
        # Construct via offset so the float lands just under the threshold.
        value = 1200.00000005 * 0.1
        assert engineering_to_transmission(value, multiplier=0.1, offset=0.0) == 1200

    def test_fraction_above_threshold_rounds_up(self) -> None:
        # raw = 1200.6 -> fract 0.6 > 1e-7 -> round to 1201
        value = 1200.6 * 0.1
        assert engineering_to_transmission(value, multiplier=0.1, offset=0.0) == 1201

    def test_fraction_above_threshold_rounds_down(self) -> None:
        # raw = 1200.4 -> fract 0.4 > 1e-7 -> round to 1200
        value = 1200.4 * 0.1
        assert engineering_to_transmission(value, multiplier=0.1, offset=0.0) == 1200

    def test_half_rounds_away_from_zero_positive(self) -> None:
        # raw = 2.5 -> round half away from zero -> 3 (banker's would give 2)
        assert engineering_to_transmission(2.5, multiplier=1.0, offset=0.0) == 3

    def test_half_rounds_away_from_zero_negative(self) -> None:
        # raw = -2.5 -> round half away from zero -> -3 (banker's would give -2)
        assert engineering_to_transmission(-2.5, multiplier=1.0, offset=0.0) == -3

    def test_half_rounds_away_from_zero_positive_odd(self) -> None:
        # raw = 3.5 -> 4 (banker's would give 4 too, but half-away is unambiguous)
        assert engineering_to_transmission(3.5, multiplier=1.0, offset=0.0) == 4

    def test_half_rounds_away_from_zero_even_boundary(self) -> None:
        # raw = 1.5 -> half away from zero -> 2 (banker's would also give 2 here);
        # raw = 0.5 -> half away from zero -> 1 (banker's would give 0). This is
        # the case that distinguishes the two rounding modes.
        assert engineering_to_transmission(0.5, multiplier=1.0, offset=0.0) == 1


class TestGuards:
    def test_zero_multiplier_raises(self) -> None:
        with pytest.raises(ScalingError, match="multiplier"):
            engineering_to_transmission(10.0, multiplier=0.0, offset=0.0)

    def test_non_finite_multiplier_raises(self) -> None:
        with pytest.raises(ScalingError, match=r"[Mm]ultiplier"):
            engineering_to_transmission(10.0, multiplier=math.inf, offset=0.0)

    def test_non_finite_offset_raises(self) -> None:
        with pytest.raises(ScalingError, match=r"[Oo]ffset"):
            engineering_to_transmission(10.0, multiplier=1.0, offset=math.nan)

    def test_out_of_range_high_raises(self) -> None:
        # raw = 3e9 / 1 exceeds i32 max
        with pytest.raises(ScalingError, match="range"):
            engineering_to_transmission(3_000_000_000.0, multiplier=1.0, offset=0.0)

    def test_out_of_range_low_raises(self) -> None:
        with pytest.raises(ScalingError, match="range"):
            engineering_to_transmission(-3_000_000_000.0, multiplier=1.0, offset=0.0)


class TestInverse:
    """transmission -> engineering is raw * multiplier + offset."""

    def test_inverse_basic(self) -> None:
        assert transmission_to_engineering(1200, multiplier=0.1, offset=0.0) == pytest.approx(120.0)

    def test_inverse_with_offset(self) -> None:
        assert transmission_to_engineering(40, multiplier=0.5, offset=5.0) == pytest.approx(25.0)

    def test_round_trip_stable(self) -> None:
        # transmission -> engineering -> transmission must return the same int.
        multiplier, offset = 0.1, 3.0
        for original in (0, 1, -1, 1200, -5000, 2_147_483_647, -2_147_483_648):
            eng = transmission_to_engineering(original, multiplier, offset)
            back = engineering_to_transmission(eng, multiplier, offset)
            assert back == original, f"round trip failed for {original}"
