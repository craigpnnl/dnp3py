"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_data() -> bytes:
    """Sample data for testing."""
    return b"123456789"
