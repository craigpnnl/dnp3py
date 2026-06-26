"""Pytest configuration and fixtures."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (cross-repo integration, cargo build, etc.)",
    )


@pytest.fixture
def sample_data() -> bytes:
    """Sample data for testing."""
    return b"123456789"
