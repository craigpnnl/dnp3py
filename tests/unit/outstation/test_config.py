"""Tests for outstation configuration."""

import pytest

from dnp3.database import DatabaseConfig
from dnp3.outstation.config import OutstationConfig, UnsolicitedConfig


class TestUnsolicitedConfig:
    """Tests for UnsolicitedConfig."""

    def test_default_values(self) -> None:
        """Default values are sensible."""
        config = UnsolicitedConfig()
        assert config.enabled is True
        assert config.class_1_enabled is True
        assert config.class_2_enabled is True
        assert config.class_3_enabled is True
        assert config.startup_retry_count == 3
        assert config.confirm_timeout == 5.0
        assert config.retry_delay == 2.0
        assert config.max_retries == 3
        assert config.hold_time_after_class == 0.0

    def test_custom_values(self) -> None:
        """Can set custom values."""
        config = UnsolicitedConfig(
            enabled=False,
            class_1_enabled=False,
            class_2_enabled=True,
            class_3_enabled=False,
            startup_retry_count=5,
            confirm_timeout=10.0,
        )
        assert config.enabled is False
        assert config.class_1_enabled is False
        assert config.class_2_enabled is True
        assert config.class_3_enabled is False
        assert config.startup_retry_count == 5
        assert config.confirm_timeout == 10.0

    def test_immutable(self) -> None:
        """Config is immutable (frozen)."""
        config = UnsolicitedConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]


class TestOutstationConfig:
    """Tests for OutstationConfig."""

    def test_default_values(self) -> None:
        """Default values are sensible."""
        config = OutstationConfig()
        assert config.address == 1
        assert config.master_address == 0
        assert config.max_fragment_size == 2048
        assert config.select_timeout == 10.0
        assert config.confirm_timeout == 5.0
        assert config.broadcast_enabled is False
        assert config.max_controls_per_request == 16
        assert config.enable_self_address is False
        assert config.time_sync_required is True

    def test_custom_values(self) -> None:
        """Can set custom values."""
        config = OutstationConfig(
            address=10,
            master_address=1,
            max_fragment_size=4096,
            select_timeout=30.0,
        )
        assert config.address == 10
        assert config.master_address == 1
        assert config.max_fragment_size == 4096
        assert config.select_timeout == 30.0

    def test_with_unsolicited_config(self) -> None:
        """Can set unsolicited config."""
        unsolicited = UnsolicitedConfig(enabled=False)
        config = OutstationConfig(unsolicited=unsolicited)
        assert config.unsolicited.enabled is False

    def test_with_database_config(self) -> None:
        """Can set database config."""
        database = DatabaseConfig(max_binary_inputs=50)
        config = OutstationConfig(database=database)
        assert config.database.max_binary_inputs == 50

    def test_address_validation_min(self) -> None:
        """Address minimum is 0."""
        config = OutstationConfig(address=0)
        assert config.address == 0

    def test_address_validation_max(self) -> None:
        """Address maximum is 65519."""
        config = OutstationConfig(address=65519)
        assert config.address == 65519

    def test_address_validation_negative(self) -> None:
        """Negative address raises ValueError."""
        with pytest.raises(ValueError, match="Address must be"):
            OutstationConfig(address=-1)

    def test_address_validation_too_large(self) -> None:
        """Address > 65519 raises ValueError."""
        with pytest.raises(ValueError, match="Address must be"):
            OutstationConfig(address=65520)

    def test_master_address_validation_min(self) -> None:
        """Master address minimum is 0."""
        config = OutstationConfig(master_address=0)
        assert config.master_address == 0

    def test_master_address_validation_max(self) -> None:
        """Master address maximum is 65535."""
        config = OutstationConfig(master_address=65535)
        assert config.master_address == 65535

    def test_master_address_validation_negative(self) -> None:
        """Negative master address raises ValueError."""
        with pytest.raises(ValueError, match="Master address must be"):
            OutstationConfig(master_address=-1)

    def test_max_fragment_size_min(self) -> None:
        """Max fragment size minimum is 249."""
        config = OutstationConfig(max_fragment_size=249)
        assert config.max_fragment_size == 249

    def test_max_fragment_size_too_small(self) -> None:
        """Max fragment size < 249 raises ValueError."""
        with pytest.raises(ValueError, match="Max fragment size must be"):
            OutstationConfig(max_fragment_size=248)

    def test_select_timeout_must_be_positive(self) -> None:
        """Select timeout must be > 0."""
        with pytest.raises(ValueError, match="Select timeout must be"):
            OutstationConfig(select_timeout=0)

    def test_confirm_timeout_must_be_positive(self) -> None:
        """Confirm timeout must be > 0."""
        with pytest.raises(ValueError, match="Confirm timeout must be"):
            OutstationConfig(confirm_timeout=0)

    def test_max_controls_must_be_positive(self) -> None:
        """Max controls must be > 0."""
        with pytest.raises(ValueError, match="Max controls must be"):
            OutstationConfig(max_controls_per_request=0)

    def test_immutable(self) -> None:
        """Config is immutable (frozen)."""
        config = OutstationConfig()
        with pytest.raises(AttributeError):
            config.address = 10  # type: ignore[misc]
