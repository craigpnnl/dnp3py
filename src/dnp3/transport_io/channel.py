"""Abstract channel interface for DNP3 I/O.

Channels provide the transport-agnostic interface for sending and receiving
bytes between DNP3 master and outstation implementations.
"""

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol, runtime_checkable


class ChannelState(Enum):
    """Channel connection state."""

    CLOSED = auto()
    OPENING = auto()
    OPEN = auto()
    CLOSING = auto()


@dataclass
class ChannelStatistics:
    """Statistics for a channel.

    Attributes:
        bytes_sent: Total bytes sent.
        bytes_received: Total bytes received.
        messages_sent: Total messages/frames sent.
        messages_received: Total messages/frames received.
        errors: Total errors encountered.
        connect_count: Number of successful connections.
        disconnect_count: Number of disconnections.
    """

    bytes_sent: int = 0
    bytes_received: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    errors: int = 0
    connect_count: int = 0
    disconnect_count: int = 0

    def reset(self) -> None:
        """Reset all statistics to zero."""
        self.bytes_sent = 0
        self.bytes_received = 0
        self.messages_sent = 0
        self.messages_received = 0
        self.errors = 0
        self.connect_count = 0
        self.disconnect_count = 0


@dataclass
class ChannelConfig:
    """Base configuration for channels.

    Attributes:
        read_buffer_size: Size of read buffer in bytes.
        write_buffer_size: Size of write buffer in bytes.
        connect_timeout: Connection timeout in seconds.
        read_timeout: Read timeout in seconds (0 = no timeout).
        write_timeout: Write timeout in seconds (0 = no timeout).
    """

    read_buffer_size: int = 4096
    write_buffer_size: int = 4096
    connect_timeout: float = 10.0
    read_timeout: float = 0.0
    write_timeout: float = 0.0


@runtime_checkable
class Channel(Protocol):
    """Protocol for DNP3 communication channels.

    Channels abstract the underlying transport (TCP, serial, etc.)
    and provide async read/write operations for byte streams.
    """

    @property
    @abstractmethod
    def state(self) -> ChannelState:
        """Get current channel state."""
        ...

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Check if channel is open and ready for I/O."""
        ...

    @property
    @abstractmethod
    def statistics(self) -> ChannelStatistics:
        """Get channel statistics."""
        ...

    @abstractmethod
    async def open(self) -> None:
        """Open the channel.

        Raises:
            ChannelError: If channel cannot be opened.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the channel gracefully."""
        ...

    @abstractmethod
    async def read(self, max_bytes: int) -> bytes:
        """Read up to max_bytes from the channel.

        Args:
            max_bytes: Maximum number of bytes to read.

        Returns:
            Bytes read (may be less than max_bytes).
            Empty bytes indicates end of stream.

        Raises:
            ChannelError: If read fails.
            ChannelClosedError: If channel is closed.
        """
        ...

    @abstractmethod
    async def write(self, data: bytes) -> int:
        """Write data to the channel.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.

        Raises:
            ChannelError: If write fails.
            ChannelClosedError: If channel is closed.
        """
        ...

    @abstractmethod
    async def read_exactly(self, num_bytes: int) -> bytes:
        """Read exactly num_bytes from the channel.

        Args:
            num_bytes: Exact number of bytes to read.

        Returns:
            Exactly num_bytes of data.

        Raises:
            ChannelError: If read fails.
            ChannelClosedError: If channel is closed or EOF before num_bytes.
        """
        ...

    @abstractmethod
    async def write_all(self, data: bytes) -> None:
        """Write all data to the channel.

        Args:
            data: Bytes to write.

        Raises:
            ChannelError: If write fails.
            ChannelClosedError: If channel is closed.
        """
        ...


@runtime_checkable
class ServerChannel(Protocol):
    """Protocol for server-side channels that accept connections.

    Server channels listen for incoming connections and create
    Channel instances for each accepted connection.
    """

    @property
    @abstractmethod
    def state(self) -> ChannelState:
        """Get current server state."""
        ...

    @property
    @abstractmethod
    def is_listening(self) -> bool:
        """Check if server is listening for connections."""
        ...

    @property
    @abstractmethod
    def local_address(self) -> tuple[str, int] | None:
        """Get local address (host, port) if listening."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start listening for connections.

        Raises:
            ChannelError: If server cannot start.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and close all connections."""
        ...

    @abstractmethod
    async def accept(self) -> Channel:
        """Accept an incoming connection.

        Returns:
            Channel for the accepted connection.

        Raises:
            ChannelError: If accept fails.
            ChannelClosedError: If server is stopped.
        """
        ...


class ChannelError(Exception):
    """Base exception for channel errors."""

    pass


class ChannelClosedError(ChannelError):
    """Raised when operation attempted on closed channel."""

    pass


class ChannelTimeoutError(ChannelError):
    """Raised when channel operation times out."""

    pass


class ChannelConnectionError(ChannelError):
    """Raised when connection fails."""

    pass


@dataclass
class TcpConfig(ChannelConfig):
    """Configuration for TCP channels.

    Attributes:
        host: Host address to connect to or bind to.
        port: Port number.
        nodelay: Enable TCP_NODELAY (disable Nagle's algorithm).
        keepalive: Enable TCP keepalive.
        keepalive_idle: Keepalive idle time in seconds.
        keepalive_interval: Keepalive interval in seconds.
        keepalive_count: Keepalive probe count.
    """

    host: str = "127.0.0.1"
    port: int = 20000
    nodelay: bool = True
    keepalive: bool = True
    keepalive_idle: float = 60.0
    keepalive_interval: float = 10.0
    keepalive_count: int = 3


@dataclass
class TcpServerConfig(TcpConfig):
    """Configuration for TCP server channels.

    Attributes:
        backlog: Maximum pending connections queue length.
        reuse_address: Enable SO_REUSEADDR.
        max_connections: Maximum concurrent connections (0 = unlimited).
    """

    backlog: int = 5
    reuse_address: bool = True
    max_connections: int = 0


@dataclass
class SimulatorConfig(ChannelConfig):
    """Configuration for simulator channels.

    Attributes:
        latency: Simulated latency in seconds.
        packet_loss: Simulated packet loss rate (0.0 to 1.0).
        bandwidth_limit: Simulated bandwidth limit in bytes/second (0 = unlimited).
        buffer_size: Internal buffer size for queued data.
    """

    latency: float = 0.0
    packet_loss: float = 0.0
    bandwidth_limit: int = 0
    buffer_size: int = 65536
