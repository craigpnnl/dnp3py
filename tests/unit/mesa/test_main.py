"""Smoke tests for the dnp3.mesa CLI entry point (__main__.py).

These tests exercise arg-parse paths and outstation construction without
actually binding a TCP port or running the event loop.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dnp3.mesa.__main__ import _packaged_profile_path

FIXTURE_PROFILE = Path(__file__).parent / "fixtures" / "test_profile.json"

# Bundled full.json census, cross-checked against
# tests/unit/mesa/test_profile.py::TestGoldenFullProfile and
# tests/integration/test_mesa_outstation.py.
FULL_PROFILE_BI = 329
FULL_PROFILE_BO = 66
FULL_PROFILE_AI = 1527
FULL_PROFILE_AO = 1197
FULL_PROFILE_CTR = 8
FULL_PROFILE_CURVES = 4


class TestMainArgParse:
    """Verify CLI argument parsing and outstation build, no TCP."""

    def test_missing_profile_uses_packaged_full_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Omitting --profile and --profile-name falls back to the packaged
        full.json, resolved via importlib.resources, not a required flag."""
        from dnp3.mesa.__main__ import main

        with patch.object(sys, "argv", ["dnp3.mesa"]), patch("asyncio.run"):
            main()

        out = capsys.readouterr().out
        profile_line = next(line for line in out.splitlines() if line.strip().startswith("Profile:"))
        resolved = Path(profile_line.split("Profile:", 1)[1].strip())
        assert resolved == _packaged_profile_path("full.json")
        assert resolved.exists()
        # Field-value assertions on the actual database registration, not just
        # "printed something": the packaged full.json census.
        assert f"{FULL_PROFILE_BI} BI" in out
        assert f"{FULL_PROFILE_BO} BO" in out
        assert f"{FULL_PROFILE_AI} AI" in out
        assert f"{FULL_PROFILE_AO} AO" in out
        assert f"{FULL_PROFILE_CTR} CTR" in out
        assert re.search(rf"Curves:\s*{FULL_PROFILE_CURVES}\b", out)

    def test_profile_name_full_resolves_packaged_full_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--profile-name full resolves to the same packaged file as the default."""
        from dnp3.mesa.__main__ import main

        with patch.object(sys, "argv", ["dnp3.mesa", "--profile-name", "full"]), patch("asyncio.run"):
            main()

        out = capsys.readouterr().out
        profile_line = next(line for line in out.splitlines() if line.strip().startswith("Profile:"))
        resolved = Path(profile_line.split("Profile:", 1)[1].strip())
        assert resolved == _packaged_profile_path("full.json")

    def test_profile_name_minimal_1547_resolves_correct_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--profile-name selects among the bundled conformance subsets."""
        from dnp3.mesa.__main__ import main

        with patch.object(sys, "argv", ["dnp3.mesa", "--profile-name", "minimal_1547"]), patch("asyncio.run"):
            main()

        out = capsys.readouterr().out
        profile_line = next(line for line in out.splitlines() if line.strip().startswith("Profile:"))
        resolved = Path(profile_line.split("Profile:", 1)[1].strip())
        assert resolved == _packaged_profile_path("minimal_1547.json")
        assert resolved.exists()
        # A genuine subset: fewer points than the full profile.
        assert f"{FULL_PROFILE_BI} BI" not in out

    def test_profile_and_profile_name_are_mutually_exclusive(self) -> None:
        """Supplying both --profile and --profile-name is a usage error."""
        from dnp3.mesa.__main__ import main

        with (
            pytest.raises(SystemExit) as exc_info,
            patch.object(
                sys,
                "argv",
                ["dnp3.mesa", "--profile", str(FIXTURE_PROFILE), "--profile-name", "full"],
            ),
        ):
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
        startup banner including CTR and curve counts. asyncio.run is patched
        so no socket is opened. The fixture profile carries 2 CTR points and
        1 curve; the summary line must report those exact counts, not just
        the pre-existing BI/BO/AI/AO counts."""
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
        assert "2 CTR" in out
        assert re.search(r"Curves:\s*1\b", out)
