"""Tests for master configuration."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.master.config import (
    MAX_MASTER_ADDRESS,
    MAX_OUTSTATION_ADDRESS,
    MIN_FRAGMENT_SIZE,
    MasterConfig,
    PollingConfig,
)


class TestPollingConfig:
    """Tests for PollingConfig."""

    def test_default_values(self) -> None:
        """Test default polling configuration."""
        config = PollingConfig()

        assert config.integrity_poll_interval == 3600.0
        assert config.class_1_poll_interval == 0.0
        assert config.class_2_poll_interval == 0.0
        assert config.class_3_poll_interval == 0.0
        assert config.response_timeout == 5.0
        assert config.retry_count == 2

    def test_custom_values(self) -> None:
        """Test custom polling configuration."""
        config = PollingConfig(
            integrity_poll_interval=1800.0,
            class_1_poll_interval=10.0,
            class_2_poll_interval=30.0,
            class_3_poll_interval=60.0,
            response_timeout=10.0,
            retry_count=3,
        )

        assert config.integrity_poll_interval == 1800.0
        assert config.class_1_poll_interval == 10.0
        assert config.class_2_poll_interval == 30.0
        assert config.class_3_poll_interval == 60.0
        assert config.response_timeout == 10.0
        assert config.retry_count == 3

    def test_is_frozen(self) -> None:
        """Test that PollingConfig is frozen."""
        config = PollingConfig()
        with pytest.raises(AttributeError):
            config.integrity_poll_interval = 100.0  # type: ignore[misc]

    @given(
        integrity=st.floats(min_value=0.0, max_value=86400.0),
        class_1=st.floats(min_value=0.0, max_value=3600.0),
        class_2=st.floats(min_value=0.0, max_value=3600.0),
        class_3=st.floats(min_value=0.0, max_value=3600.0),
    )
    def test_property_based(
        self,
        integrity: float,
        class_1: float,
        class_2: float,
        class_3: float,
    ) -> None:
        """Test polling config with various values."""
        config = PollingConfig(
            integrity_poll_interval=integrity,
            class_1_poll_interval=class_1,
            class_2_poll_interval=class_2,
            class_3_poll_interval=class_3,
        )

        assert config.integrity_poll_interval == integrity
        assert config.class_1_poll_interval == class_1
        assert config.class_2_poll_interval == class_2
        assert config.class_3_poll_interval == class_3


class TestMasterConfig:
    """Tests for MasterConfig."""

    def test_default_values(self) -> None:
        """Test default master configuration."""
        config = MasterConfig()

        assert config.address == 1
        assert config.outstation_address == 10
        assert config.max_fragment_size == 2048
        assert config.response_timeout == 5.0
        assert config.confirm_timeout == 5.0
        assert config.task_retry_count == 2
        assert config.enable_unsolicited is True
        assert config.startup_integrity_poll is True
        assert config.disable_unsolicited_on_startup is False
        assert config.enable_unsolicited_on_startup is True
        assert config.time_sync_on_startup is False
        assert isinstance(config.polling, PollingConfig)

    def test_custom_values(self) -> None:
        """Test custom master configuration."""
        polling = PollingConfig(integrity_poll_interval=1800.0)
        config = MasterConfig(
            address=5,
            outstation_address=100,
            max_fragment_size=1024,
            response_timeout=10.0,
            confirm_timeout=8.0,
            task_retry_count=3,
            enable_unsolicited=False,
            startup_integrity_poll=False,
            polling=polling,
        )

        assert config.address == 5
        assert config.outstation_address == 100
        assert config.max_fragment_size == 1024
        assert config.response_timeout == 10.0
        assert config.confirm_timeout == 8.0
        assert config.task_retry_count == 3
        assert config.enable_unsolicited is False
        assert config.startup_integrity_poll is False
        assert config.polling.integrity_poll_interval == 1800.0

    def test_invalid_address_negative(self) -> None:
        """Test that negative address raises error."""
        with pytest.raises(ValueError, match="Address must be"):
            MasterConfig(address=-1)

    def test_invalid_address_too_large(self) -> None:
        """Test that address > MAX_MASTER_ADDRESS raises error."""
        with pytest.raises(ValueError, match="Address must be"):
            MasterConfig(address=MAX_MASTER_ADDRESS + 1)

    def test_invalid_outstation_address_negative(self) -> None:
        """Test that negative outstation address raises error."""
        with pytest.raises(ValueError, match="Outstation address must be"):
            MasterConfig(outstation_address=-1)

    def test_invalid_outstation_address_too_large(self) -> None:
        """Test that outstation address > 65535 raises error."""
        with pytest.raises(ValueError, match="Outstation address must be"):
            MasterConfig(outstation_address=MAX_OUTSTATION_ADDRESS + 1)

    def test_invalid_fragment_size_too_small(self) -> None:
        """Test that fragment size < MIN_FRAGMENT_SIZE raises error."""
        with pytest.raises(ValueError, match="Max fragment size must be"):
            MasterConfig(max_fragment_size=MIN_FRAGMENT_SIZE - 1)

    def test_invalid_response_timeout_zero(self) -> None:
        """Test that response timeout <= 0 raises error."""
        with pytest.raises(ValueError, match="Response timeout must be"):
            MasterConfig(response_timeout=0)

    def test_invalid_response_timeout_negative(self) -> None:
        """Test that response timeout < 0 raises error."""
        with pytest.raises(ValueError, match="Response timeout must be"):
            MasterConfig(response_timeout=-1.0)

    def test_invalid_confirm_timeout_zero(self) -> None:
        """Test that confirm timeout <= 0 raises error."""
        with pytest.raises(ValueError, match="Confirm timeout must be"):
            MasterConfig(confirm_timeout=0)

    def test_invalid_task_retry_count_negative(self) -> None:
        """Test that negative retry count raises error."""
        with pytest.raises(ValueError, match="Task retry count must be"):
            MasterConfig(task_retry_count=-1)

    def test_valid_boundary_addresses(self) -> None:
        """Test valid boundary addresses."""
        # Minimum addresses
        config = MasterConfig(address=0, outstation_address=0)
        assert config.address == 0
        assert config.outstation_address == 0

        # Maximum addresses
        config = MasterConfig(
            address=MAX_MASTER_ADDRESS,
            outstation_address=MAX_OUTSTATION_ADDRESS,
        )
        assert config.address == MAX_MASTER_ADDRESS
        assert config.outstation_address == MAX_OUTSTATION_ADDRESS

    def test_is_frozen(self) -> None:
        """Test that MasterConfig is frozen."""
        config = MasterConfig()
        with pytest.raises(AttributeError):
            config.address = 5  # type: ignore[misc]

    @given(
        address=st.integers(min_value=0, max_value=MAX_MASTER_ADDRESS),
        outstation_addr=st.integers(min_value=0, max_value=MAX_OUTSTATION_ADDRESS),
        timeout=st.floats(min_value=0.1, max_value=120.0),
        retries=st.integers(min_value=0, max_value=10),
    )
    def test_property_based_valid_config(
        self,
        address: int,
        outstation_addr: int,
        timeout: float,
        retries: int,
    ) -> None:
        """Test master config with various valid values."""
        config = MasterConfig(
            address=address,
            outstation_address=outstation_addr,
            response_timeout=timeout,
            task_retry_count=retries,
        )

        assert config.address == address
        assert config.outstation_address == outstation_addr
        assert config.response_timeout == timeout
        assert config.task_retry_count == retries
