"""Smoke tests for the dnp3.mesa CLI entry point (__main__.py).

These tests exercise arg-parse paths and outstation construction without
actually binding a TCP port or running the event loop.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURE_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.json"


class TestMainArgParse:
    """Verify CLI argument parsing and outstation build, no TCP."""

    def test_missing_profile_exits_with_error(self) -> None:
        """--profile is required; omitting it causes SystemExit."""
        from dnp3.mesa.__main__ import main

        with pytest.raises(SystemExit) as exc_info, patch.object(sys, "argv", ["dnp3.mesa"]):
            main()
        assert exc_info.value.code != 0

    def test_nonexistent_profile_raises(self, tmp_path: Path) -> None:
        """--profile pointing at a non-existent file raises FileNotFoundError
        before any async code runs (load_profile is called synchronously)."""
        from dnp3.mesa.__main__ import main

        missing = tmp_path / "missing.json"
        # Patch asyncio.run so the event loop never starts; the error must surface
        # from create_mesa_outstation, which runs synchronously inside main().
        with (
            pytest.raises(FileNotFoundError),
            patch.object(sys, "argv", ["dnp3.mesa", "--profile", str(missing)]),
            patch("asyncio.run"),
        ):
            main()

    def test_valid_profile_builds_outstation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """With a valid --profile, main() builds the outstation and prints a
        startup banner. asyncio.run is patched so no socket is opened."""
        from dnp3.mesa.__main__ import main

        with (
            patch.object(
                sys,
                "argv",
                ["dnp3.mesa", "--profile", str(FIXTURE_PROFILE), "--port", "20001"],
            ),
            patch("asyncio.run"),
        ):
            main()

        out = capsys.readouterr().out
        assert "MESA Outstation starting" in out
        assert "BI" in out or "AI" in out  # at least one point-type count printed
