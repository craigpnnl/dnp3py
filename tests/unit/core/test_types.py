"""Tests for core type definitions."""

from dnp3.core.types import (
    BROADCAST_ADDRESS,
    MAX_ADDRESS,
    Address,
    LinkAddresses,
    PointIndex,
)


class TestAddress:
    """Tests for Address type."""

    def test_valid_address(self) -> None:
        """Create valid addresses."""
        addr = Address(1)
        assert addr == 1

    def test_zero_address(self) -> None:
        """Zero is a valid address."""
        addr = Address(0)
        assert addr == 0

    def test_max_address(self) -> None:
        """Maximum address value."""
        addr = Address(65534)
        assert addr == 65534
        assert addr == MAX_ADDRESS

    def test_broadcast_address(self) -> None:
        """Broadcast address is 0xFFFF."""
        assert BROADCAST_ADDRESS == 0xFFFF
        assert BROADCAST_ADDRESS == 65535


class TestLinkAddresses:
    """Tests for LinkAddresses dataclass."""

    def test_create_link_addresses(self) -> None:
        """Create link addresses pair."""
        addrs = LinkAddresses(source=Address(1), destination=Address(2))
        assert addrs.source == 1
        assert addrs.destination == 2

    def test_link_addresses_immutable(self) -> None:
        """LinkAddresses should be frozen."""
        addrs = LinkAddresses(source=Address(1), destination=Address(2))
        # Frozen dataclass raises FrozenInstanceError on assignment
        try:
            addrs.source = Address(99)  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass  # Expected for frozen dataclass

    def test_link_addresses_equality(self) -> None:
        """Equal addresses compare equal."""
        addrs1 = LinkAddresses(source=Address(1), destination=Address(2))
        addrs2 = LinkAddresses(source=Address(1), destination=Address(2))
        assert addrs1 == addrs2

    def test_link_addresses_inequality(self) -> None:
        """Different addresses compare not equal."""
        addrs1 = LinkAddresses(source=Address(1), destination=Address(2))
        addrs2 = LinkAddresses(source=Address(1), destination=Address(3))
        assert addrs1 != addrs2


class TestPointIndex:
    """Tests for PointIndex type."""

    def test_valid_point_index(self) -> None:
        """Create valid point index."""
        idx = PointIndex(0)
        assert idx == 0

    def test_large_point_index(self) -> None:
        """Large point indices are valid."""
        idx = PointIndex(65535)
        assert idx == 65535
