"""TCP client channel for DNP3 communication.

Provides an async TCP client implementation for connecting to
DNP3 outstations or other TCP-based DNP3 endpoints.
"""

import asyncio
import socket
from dataclasses import dataclass, field

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelConnectionError,
    ChannelError,
    ChannelState,
    ChannelStatistics,
    ChannelTimeoutError,
    TcpConfig,
)


@dataclass
class TcpClientChannel:
    """TCP client channel for DNP3 communication.

    Connects to a remote TCP server and provides async read/write operations.

    Attributes:
        config: TCP configuration.
    """

    config: TcpConfig = field(default_factory=TcpConfig)

    _state: ChannelState = field(default=ChannelState.CLOSED, init=False)
    _statistics: ChannelStatistics = field(default_factory=ChannelStatistics, init=False)
    _reader: asyncio.StreamReader | None = field(default=None, init=False)
    _writer: asyncio.StreamWriter | None = field(default=None, init=False)

    @property
    def state(self) -> ChannelState:
        """Get current channel state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if channel is open and ready for I/O."""
        return self._state == ChannelState.OPEN

    @property
    def statistics(self) -> ChannelStatistics:
        """Get channel statistics."""
        return self._statistics

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Get local address (host, port) if connected."""
        if self._writer is not None:
            try:
                sockname = self._writer.get_extra_info("sockname")
                if sockname:
                    return (sockname[0], sockname[1])
            except (AttributeError, IndexError):
                pass
        return None

    @property
    def remote_address(self) -> tuple[str, int] | None:
        """Get remote address (host, port) if connected."""
        if self._writer is not None:
            try:
                peername = self._writer.get_extra_info("peername")
                if peername:
                    return (peername[0], peername[1])
            except (AttributeError, IndexError):
                pass
        return None

    async def open(self) -> None:
        """Open the channel by connecting to the remote server.

        Raises:
            ChannelConnectionError: If connection fails.
            ChannelTimeoutError: If connection times out.
        """
        if self._state == ChannelState.OPEN:
            return

        self._state = ChannelState.OPENING

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host=self.config.host,
                    port=self.config.port,
                ),
                timeout=self.config.connect_timeout,
            )

            # Configure socket options
            assert self._writer is not None  # Just assigned above
            sock = self._writer.get_extra_info("socket")
            if sock is not None:
                self._configure_socket(sock)

            self._state = ChannelState.OPEN
            self._statistics.connect_count += 1

        except TimeoutError as e:
            self._state = ChannelState.CLOSED
            raise ChannelTimeoutError(f"Connection to {self.config.host}:{self.config.port} timed out") from e
        except OSError as e:
            self._state = ChannelState.CLOSED
            raise ChannelConnectionError(f"Failed to connect to {self.config.host}:{self.config.port}: {e}") from e

    def _configure_socket(self, sock: socket.socket) -> None:
        """Configure socket options.

        Args:
            sock: Socket to configure.
        """
        # TCP_NODELAY - disable Nagle's algorithm
        if self.config.nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # SO_KEEPALIVE - enable keepalive
        if self.config.keepalive:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # Platform-specific keepalive options
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPIDLE,
                    int(self.config.keepalive_idle),
                )
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPINTVL,
                    int(self.config.keepalive_interval),
                )
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPCNT,
                    self.config.keepalive_count,
                )

    async def close(self) -> None:
        """Close the channel gracefully."""
        if self._state == ChannelState.CLOSED:
            return

        self._state = ChannelState.CLOSING

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except (OSError, ConnectionError):
                pass  # Ignore errors during close

        self._writer = None
        self._reader = None
        self._state = ChannelState.CLOSED
        self._statistics.disconnect_count += 1

    async def read(self, max_bytes: int) -> bytes:
        """Read up to max_bytes from the channel.

        Args:
            max_bytes: Maximum number of bytes to read.

        Returns:
            Bytes read. Empty bytes indicates EOF.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelTimeoutError: If read times out.
            ChannelError: If read fails.
        """
        if self._state != ChannelState.OPEN or self._reader is None:
            raise ChannelClosedError("Channel is not open")

        try:
            timeout = self.config.read_timeout if self.config.read_timeout > 0 else None
            data = await asyncio.wait_for(
                self._reader.read(max_bytes),
                timeout=timeout,
            )
            if data:
                self._statistics.bytes_received += len(data)
                self._statistics.messages_received += 1
            return data
        except TimeoutError as e:
            raise ChannelTimeoutError("Read timed out") from e
        except (OSError, ConnectionError) as e:
            self._statistics.errors += 1
            raise ChannelError(f"Read failed: {e}") from e

    async def write(self, data: bytes) -> int:
        """Write data to the channel.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelTimeoutError: If write times out.
            ChannelError: If write fails.
        """
        if self._state != ChannelState.OPEN or self._writer is None:
            raise ChannelClosedError("Channel is not open")

        try:
            self._writer.write(data)
            timeout = self.config.write_timeout if self.config.write_timeout > 0 else None
            await asyncio.wait_for(
                self._writer.drain(),
                timeout=timeout,
            )
            self._statistics.bytes_sent += len(data)
            self._statistics.messages_sent += 1
            return len(data)
        except TimeoutError as e:
            raise ChannelTimeoutError("Write timed out") from e
        except (OSError, ConnectionError) as e:
            self._statistics.errors += 1
            raise ChannelError(f"Write failed: {e}") from e

    async def read_exactly(self, num_bytes: int) -> bytes:
        """Read exactly num_bytes from the channel.

        Args:
            num_bytes: Exact number of bytes to read.

        Returns:
            Exactly num_bytes of data.

        Raises:
            ChannelClosedError: If channel is closed or EOF.
            ChannelTimeoutError: If read times out.
            ChannelError: If read fails.
        """
        if self._state != ChannelState.OPEN or self._reader is None:
            raise ChannelClosedError("Channel is not open")

        try:
            timeout = self.config.read_timeout if self.config.read_timeout > 0 else None
            data = await asyncio.wait_for(
                self._reader.readexactly(num_bytes),
                timeout=timeout,
            )
            self._statistics.bytes_received += len(data)
            self._statistics.messages_received += 1
            return data
        except asyncio.IncompleteReadError as e:
            raise ChannelClosedError(f"EOF before reading {num_bytes} bytes (got {len(e.partial)})") from e
        except TimeoutError as e:
            raise ChannelTimeoutError("Read timed out") from e
        except (OSError, ConnectionError) as e:
            self._statistics.errors += 1
            raise ChannelError(f"Read failed: {e}") from e

    async def write_all(self, data: bytes) -> None:
        """Write all data to the channel.

        Args:
            data: Bytes to write.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelTimeoutError: If write times out.
            ChannelError: If write fails.
        """
        written = await self.write(data)
        if written != len(data):
            raise ChannelError(f"Only wrote {written} of {len(data)} bytes")

    async def __aenter__(self) -> "TcpClientChannel":
        """Async context manager entry."""
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close()


async def connect(
    host: str,
    port: int,
    config: TcpConfig | None = None,
) -> TcpClientChannel:
    """Connect to a TCP server and return an open channel.

    Args:
        host: Host to connect to.
        port: Port to connect to.
        config: Optional TCP configuration.

    Returns:
        Open TcpClientChannel.

    Raises:
        ChannelConnectionError: If connection fails.
        ChannelTimeoutError: If connection times out.
    """
    if config is None:
        config = TcpConfig(host=host, port=port)
    else:
        config = TcpConfig(
            host=host,
            port=port,
            read_buffer_size=config.read_buffer_size,
            write_buffer_size=config.write_buffer_size,
            connect_timeout=config.connect_timeout,
            read_timeout=config.read_timeout,
            write_timeout=config.write_timeout,
            nodelay=config.nodelay,
            keepalive=config.keepalive,
            keepalive_idle=config.keepalive_idle,
            keepalive_interval=config.keepalive_interval,
            keepalive_count=config.keepalive_count,
        )

    channel = TcpClientChannel(config=config)
    await channel.open()
    return channel
