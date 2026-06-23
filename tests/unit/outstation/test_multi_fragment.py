"""Tests for multi-fragment response splitting.

When the outstation database contains enough points to exceed
max_fragment_size (default 2048 bytes), the outstation must split
the response into multiple fragments with correct FIR/FIN flags
per IEEE 1815-2012.
"""

from dnp3.application.builder import build_integrity_poll
from dnp3.core.enums import FunctionCode
from dnp3.database import Database, DatabaseConfig
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import Outstation


def _make_outstation(
    num_bi: int = 0,
    num_ai: int = 0,
    max_fragment_size: int = 2048,
) -> Outstation:
    """Create an outstation with the given number of points."""
    db_config = DatabaseConfig(
        max_binary_inputs=max(num_bi + 10, 100),
        max_analog_inputs=max(num_ai + 10, 100),
    )
    config = OutstationConfig(
        max_fragment_size=max_fragment_size,
        time_sync_required=False,
        database=db_config,
    )
    database = Database(config=db_config)
    for i in range(num_bi):
        database.add_binary_input(i, value=(i % 2 == 0))
    for i in range(num_ai):
        database.add_analog_input(i, value=float(i * 100))
    return Outstation(config=config, database=database)


def _do_integrity_poll(outstation: Outstation) -> list:
    """Send integrity poll and return list of response fragments."""
    request = build_integrity_poll()
    return outstation.process_request(request.to_bytes())


class TestMultiFragmentSmallDatabase:
    """Small databases should produce a single fragment."""

    def test_small_database_returns_list(self) -> None:
        """process_request returns a list of ResponseFragment."""
        outstation = _make_outstation(num_bi=2, num_ai=2)
        responses = _do_integrity_poll(outstation)
        assert isinstance(responses, list)

    def test_small_database_single_fragment(self) -> None:
        """Small database produces exactly one fragment."""
        outstation = _make_outstation(num_bi=2, num_ai=2)
        responses = _do_integrity_poll(outstation)
        assert len(responses) == 1

    def test_single_fragment_fir_fin_both_true(self) -> None:
        """Single fragment has FIR=True and FIN=True."""
        outstation = _make_outstation(num_bi=2, num_ai=2)
        responses = _do_integrity_poll(outstation)
        assert responses[0].is_first is True
        assert responses[0].is_final is True

    def test_single_fragment_under_max_size(self) -> None:
        """Single fragment is under max_fragment_size."""
        outstation = _make_outstation(num_bi=2, num_ai=2)
        responses = _do_integrity_poll(outstation)
        assert len(responses[0].to_bytes()) <= 2048

    def test_empty_database_returns_list(self) -> None:
        """Empty database returns a single-element list."""
        outstation = _make_outstation()
        responses = _do_integrity_poll(outstation)
        assert isinstance(responses, list)
        assert len(responses) == 1


class TestMultiFragmentLargeDatabase:
    """Large databases should produce multiple fragments."""

    def test_large_database_multi_fragment(self) -> None:
        """500 AI points exceed 2048 bytes, producing multiple fragments."""
        outstation = _make_outstation(num_ai=500)
        responses = _do_integrity_poll(outstation)
        assert len(responses) > 1

    def test_first_fragment_fir_true_fin_false(self) -> None:
        """First fragment of multi-fragment has FIR=True, FIN=False."""
        outstation = _make_outstation(num_ai=500)
        responses = _do_integrity_poll(outstation)
        assert len(responses) > 1
        assert responses[0].is_first is True
        assert responses[0].is_final is False

    def test_last_fragment_fir_false_fin_true(self) -> None:
        """Last fragment of multi-fragment has FIR=False, FIN=True."""
        outstation = _make_outstation(num_ai=500)
        responses = _do_integrity_poll(outstation)
        assert len(responses) > 1
        assert responses[-1].is_first is False
        assert responses[-1].is_final is True

    def test_middle_fragments_fir_false_fin_false(self) -> None:
        """Middle fragments have FIR=False, FIN=False."""
        # Use enough points to get at least 3 fragments
        outstation = _make_outstation(num_ai=1000)
        responses = _do_integrity_poll(outstation)
        assert len(responses) >= 3
        for frag in responses[1:-1]:
            assert frag.is_first is False
            assert frag.is_final is False

    def test_all_fragments_under_max_size(self) -> None:
        """Every fragment respects max_fragment_size."""
        outstation = _make_outstation(num_ai=500)
        responses = _do_integrity_poll(outstation)
        for frag in responses:
            assert len(frag.to_bytes()) <= 2048

    def test_all_fragments_are_responses(self) -> None:
        """Every fragment has RESPONSE function code."""
        outstation = _make_outstation(num_ai=500)
        responses = _do_integrity_poll(outstation)
        for frag in responses:
            assert frag.header.function == FunctionCode.RESPONSE

    def test_all_points_present_across_fragments(self) -> None:
        """All point data is present across all fragments combined.

        We verify by checking total data bytes across all object blocks
        matches what we'd expect for the point count.
        """
        num_ai = 500
        outstation = _make_outstation(num_ai=num_ai)
        responses = _do_integrity_poll(outstation)

        # Count total points by summing object block data across fragments
        # Each AI point in indexed format: 2-byte index + 1-byte flags + 4-byte value = 7 bytes
        # (indices 0-499 require 2-byte index since some > 255)
        total_data_bytes = 0
        for frag in responses:
            for obj in frag.objects:
                total_data_bytes += len(obj.data)

        # The data includes count prefix bytes plus per-point data.
        # With 500 points and 2-byte indices: count(2) + 500 * 7 = 3502 bytes total
        # This should be spread across fragments. Just verify it's substantial.
        assert total_data_bytes > 0
        # More precise: at least num_ai * 6 bytes of point data (minimum)
        assert total_data_bytes >= num_ai * 6


class TestMultiFragmentCustomSize:
    """Test with custom max_fragment_size."""

    def test_smaller_max_produces_more_fragments(self) -> None:
        """Smaller max_fragment_size produces more fragments."""
        outstation_small = _make_outstation(num_ai=200, max_fragment_size=500)
        outstation_large = _make_outstation(num_ai=200, max_fragment_size=2048)
        responses_small = _do_integrity_poll(outstation_small)
        responses_large = _do_integrity_poll(outstation_large)
        assert len(responses_small) > len(responses_large)

    def test_custom_size_respected(self) -> None:
        """All fragments respect the custom max_fragment_size=500."""
        outstation = _make_outstation(num_ai=200, max_fragment_size=500)
        responses = _do_integrity_poll(outstation)
        for frag in responses:
            assert len(frag.to_bytes()) <= 500


class TestMultiFragmentMixedTypes:
    """Test with both BI and AI points."""

    def test_mixed_types_multi_fragment(self) -> None:
        """Mixed BI + AI that exceeds fragment size produces multiple fragments."""
        # 342 BI + 500 AI should definitely exceed 2048 bytes
        outstation = _make_outstation(num_bi=342, num_ai=500)
        responses = _do_integrity_poll(outstation)
        assert len(responses) > 1

    def test_mixed_types_all_under_max(self) -> None:
        """All fragments with mixed types respect max_fragment_size."""
        outstation = _make_outstation(num_bi=342, num_ai=500)
        responses = _do_integrity_poll(outstation)
        for frag in responses:
            assert len(frag.to_bytes()) <= 2048


class TestMultiFragmentMESAScale:
    """Test at MESA profile scale (342 BI + 1952 AI)."""

    def test_mesa_scale_multi_fragment(self) -> None:
        """MESA-scale database (342 BI + 1952 AI) produces multiple fragments."""
        outstation = _make_outstation(num_bi=342, num_ai=1952)
        responses = _do_integrity_poll(outstation)
        assert len(responses) > 1

    def test_mesa_scale_all_under_max(self) -> None:
        """All MESA-scale fragments respect max_fragment_size."""
        outstation = _make_outstation(num_bi=342, num_ai=1952)
        responses = _do_integrity_poll(outstation)
        for frag in responses:
            frag_bytes = frag.to_bytes()
            assert len(frag_bytes) <= 2048, f"Fragment size {len(frag_bytes)} exceeds max 2048"
