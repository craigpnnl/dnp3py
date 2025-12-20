"""Nox configuration for multi-Python testing."""

import nox

PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14"]


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    """Run the test suite."""
    session.install("-e", ".")
    session.install("pytest", "pytest-asyncio", "hypothesis")
    session.run("pytest", "tests/", "-v", "--tb=short")


@nox.session(python=PYTHON_VERSIONS)
def tests_cov(session: nox.Session) -> None:
    """Run tests with coverage."""
    session.install("-e", ".")
    session.install("pytest", "pytest-asyncio", "pytest-cov", "hypothesis")
    session.run(
        "pytest",
        "tests/",
        "--cov=src/dnp3",
        "--cov-report=term-missing",
        "--cov-fail-under=95",
    )


@nox.session(python="3.14")
def lint(session: nox.Session) -> None:
    """Run linting."""
    session.install("ruff")
    session.run("ruff", "check", "src/", "tests/")
    session.run("ruff", "format", "--check", "src/", "tests/")


@nox.session(python="3.14")
def typecheck(session: nox.Session) -> None:
    """Run type checking."""
    session.install("-e", ".")
    session.install("mypy")
    session.run("mypy", "src/")
