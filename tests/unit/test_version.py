"""Version accessor contract tests.

These tests cover two layers of the version contract:

1. When the package is installed, importlib.metadata.version("dnp3py")
   returns the version string derived from the installed distribution
   metadata (which comes from the VCS tag via hatch-vcs at build time).

2. When the package is NOT installed (running from source),
   dnp3.__version__ falls back to the sentinel string "dev". This is
   the observable signal that no tag-derived version is available.

The build-flag wiring (SETUPTOOLS_SCM_PRETEND_VERSION injection into the
wheel) is separately verified by the CI smoke-test job (release.yml phase 2),
which installs an actual wheel built with the synthetic sentinel and asserts
importlib.metadata.version("dnp3py") matches it exactly.
"""

import sys
from importlib.metadata import PackageNotFoundError, version
from unittest.mock import patch


def test_version_when_installed() -> None:
    """__version__ is a non-empty string when the package is installed."""
    import dnp3  # type: ignore[import]

    assert isinstance(dnp3.__version__, str)
    assert len(dnp3.__version__) > 0


def test_version_fallback_sentinel_when_not_installed() -> None:
    """__version__ falls back to 'dev' when the package is not installed.

    This simulates the PackageNotFoundError path in __init__.py,
    which fires when running directly from source without installing.
    We exercise the branch by temporarily replacing dnp3 in sys.modules
    to avoid module-reload side effects on subsequent tests.
    """
    with patch("importlib.metadata.version", side_effect=PackageNotFoundError("dnp3py")):
        # Remove the cached module so the patched version() is called on import.
        saved = sys.modules.pop("dnp3", None)
        try:
            import dnp3  # type: ignore[import]

            assert dnp3.__version__ == "dev", (
                f"Expected fallback sentinel 'dev', got {dnp3.__version__!r}. "
                "The PackageNotFoundError path in __init__.py is broken."
            )
        finally:
            # Restore the original module so other tests see the real version.
            sys.modules.pop("dnp3", None)
            if saved is not None:
                sys.modules["dnp3"] = saved


def test_importlib_metadata_version_matches_init_version() -> None:
    """importlib.metadata.version('dnp3py') and dnp3.__version__ agree when installed."""
    import dnp3  # type: ignore[import]

    try:
        meta_version = version("dnp3py")
    except PackageNotFoundError:
        import pytest

        pytest.skip("dnp3py not installed as a distribution; skipping metadata comparison.")

    assert dnp3.__version__ == meta_version, (
        f"dnp3.__version__ ({dnp3.__version__!r}) does not match "
        f"importlib.metadata.version('dnp3py') ({meta_version!r}). "
        "The version accessor in __init__.py is inconsistent with the installed distribution."
    )
