"""Outstation configuration per IEEE 1815-2012.

Configuration options for DNP3 outstation behavior, timeouts,
and unsolicited response settings.
"""

from dataclasses import dataclass, field

from dnp3.database import DatabaseConfig

# DNP3 address limits (IEEE 1815-2012)
MAX_OUTSTATION_ADDRESS = 65519  # 0xFFEF - addresses 0xFFF0-0xFFFF reserved
MAX_MASTER_ADDRESS = 65535  # 0xFFFF - can be any 16-bit value
MIN_FRAGMENT_SIZE = 249  # Minimum required by spec


@dataclass(frozen=True)
class UnsolicitedConfig:
    """Configuration for unsolicited responses.

    Attributes:
        enabled: Whether unsolicited responses are enabled.
        class_1_enabled: Enable Class 1 unsolicited.
        class_2_enabled: Enable Class 2 unsolicited.
        class_3_enabled: Enable Class 3 unsolicited.
        startup_retry_count: Number of retries during startup.
        confirm_timeout: Timeout waiting for confirm (seconds).
        retry_delay: Delay between retries (seconds).
        max_retries: Maximum number of retries before giving up.
        hold_time_after_class: Time to wait after events for more (seconds).
    """

    enabled: bool = True
    class_1_enabled: bool = True
    class_2_enabled: bool = True
    class_3_enabled: bool = True
    startup_retry_count: int = 3
    confirm_timeout: float = 5.0
    retry_delay: float = 2.0
    max_retries: int = 3
    hold_time_after_class: float = 0.0


@dataclass(frozen=True)
class OutstationConfig:
    """Outstation configuration.

    Attributes:
        address: DNP3 address of this outstation.
        master_address: Expected master address (0 for any).
        max_fragment_size: Maximum fragment size in bytes.
        select_timeout: Timeout for SELECT before OPERATE (seconds).
        confirm_timeout: Timeout waiting for confirmations (seconds).
        broadcast_enabled: Accept broadcast requests.
        unsolicited: Unsolicited response configuration.
        database: Database configuration.
        max_controls_per_request: Maximum control operations per request.
        enable_self_address: Accept messages to self address (0xFFFC).
        time_sync_required: Start with NEED_TIME IIN flag.
    """

    address: int = 1
    master_address: int = 0
    max_fragment_size: int = 2048
    select_timeout: float = 10.0
    confirm_timeout: float = 5.0
    broadcast_enabled: bool = False
    unsolicited: UnsolicitedConfig = field(default_factory=UnsolicitedConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    max_controls_per_request: int = 16
    enable_self_address: bool = False
    time_sync_required: bool = True

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not 0 <= self.address <= MAX_OUTSTATION_ADDRESS:
            msg = f"Address must be 0-{MAX_OUTSTATION_ADDRESS}, got {self.address}"
            raise ValueError(msg)
        if not 0 <= self.master_address <= MAX_MASTER_ADDRESS:
            msg = f"Master address must be 0-{MAX_MASTER_ADDRESS}, got {self.master_address}"
            raise ValueError(msg)
        if self.max_fragment_size < MIN_FRAGMENT_SIZE:
            msg = f"Max fragment size must be >= {MIN_FRAGMENT_SIZE}, got {self.max_fragment_size}"
            raise ValueError(msg)
        if self.select_timeout <= 0:
            msg = f"Select timeout must be > 0, got {self.select_timeout}"
            raise ValueError(msg)
        if self.confirm_timeout <= 0:
            msg = f"Confirm timeout must be > 0, got {self.confirm_timeout}"
            raise ValueError(msg)
        if self.max_controls_per_request <= 0:
            msg = f"Max controls must be > 0, got {self.max_controls_per_request}"
            raise ValueError(msg)
