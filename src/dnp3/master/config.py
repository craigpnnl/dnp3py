"""Master station configuration per IEEE 1815-2012.

Configuration options for DNP3 master behavior, timeouts,
and polling settings.
"""

from dataclasses import dataclass, field

# DNP3 address limits (IEEE 1815-2012)
MAX_MASTER_ADDRESS = 65519  # 0xFFEF - addresses 0xFFF0-0xFFFF reserved
MAX_OUTSTATION_ADDRESS = 65535  # 0xFFFF - can be any 16-bit value
MIN_FRAGMENT_SIZE = 249  # Minimum required by spec


@dataclass(frozen=True)
class PollingConfig:
    """Configuration for polling operations.

    Attributes:
        integrity_poll_interval: Seconds between integrity polls (0=disabled).
        class_1_poll_interval: Seconds between Class 1 polls (0=disabled).
        class_2_poll_interval: Seconds between Class 2 polls (0=disabled).
        class_3_poll_interval: Seconds between Class 3 polls (0=disabled).
        response_timeout: Timeout waiting for response (seconds).
        retry_count: Number of retries on timeout.
    """

    integrity_poll_interval: float = 3600.0  # 1 hour
    class_1_poll_interval: float = 0.0  # Disabled
    class_2_poll_interval: float = 0.0  # Disabled
    class_3_poll_interval: float = 0.0  # Disabled
    response_timeout: float = 5.0
    retry_count: int = 2


@dataclass(frozen=True)
class MasterConfig:
    """Master station configuration.

    Attributes:
        address: DNP3 address of this master.
        outstation_address: Address of the outstation to communicate with.
        max_fragment_size: Maximum fragment size in bytes.
        response_timeout: Timeout waiting for responses (seconds).
        confirm_timeout: Timeout waiting for confirmations (seconds).
        task_retry_count: Number of retries for failed tasks.
        enable_unsolicited: Accept unsolicited responses.
        startup_integrity_poll: Perform integrity poll on startup.
        disable_unsolicited_on_startup: Send DISABLE_UNSOLICITED on startup.
        enable_unsolicited_on_startup: Send ENABLE_UNSOLICITED on startup.
        time_sync_on_startup: Perform time sync on startup.
        polling: Polling configuration.
    """

    address: int = 1
    outstation_address: int = 10
    max_fragment_size: int = 2048
    response_timeout: float = 5.0
    confirm_timeout: float = 5.0
    task_retry_count: int = 2
    enable_unsolicited: bool = True
    startup_integrity_poll: bool = True
    disable_unsolicited_on_startup: bool = False
    enable_unsolicited_on_startup: bool = True
    time_sync_on_startup: bool = False
    polling: PollingConfig = field(default_factory=PollingConfig)

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not 0 <= self.address <= MAX_MASTER_ADDRESS:
            msg = f"Address must be 0-{MAX_MASTER_ADDRESS}, got {self.address}"
            raise ValueError(msg)
        if not 0 <= self.outstation_address <= MAX_OUTSTATION_ADDRESS:
            msg = f"Outstation address must be 0-{MAX_OUTSTATION_ADDRESS}"
            msg += f", got {self.outstation_address}"
            raise ValueError(msg)
        if self.max_fragment_size < MIN_FRAGMENT_SIZE:
            msg = f"Max fragment size must be >= {MIN_FRAGMENT_SIZE}, got {self.max_fragment_size}"
            raise ValueError(msg)
        if self.response_timeout <= 0:
            msg = f"Response timeout must be > 0, got {self.response_timeout}"
            raise ValueError(msg)
        if self.confirm_timeout <= 0:
            msg = f"Confirm timeout must be > 0, got {self.confirm_timeout}"
            raise ValueError(msg)
        if self.task_retry_count < 0:
            msg = f"Task retry count must be >= 0, got {self.task_retry_count}"
            raise ValueError(msg)
