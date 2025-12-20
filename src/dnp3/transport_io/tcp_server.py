"""TCP server channel for DNP3 communication.

Provides an async TCP server implementation for hosting DNP3 outstations
and accepting connections from DNP3 masters.
"""

import asyncio
import socket
from dataclasses import dataclass, field

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelError,
    ChannelState,
    ChannelStatistics,
    ChannelTimeoutError,
    TcpConfig,
    TcpServerConfig,
)


@dataclass
class TcpServerChannel:
    """Server-side TCP channel for an accepted connection.

    Created by TcpServer when a client connects.

    Attributes:
        reader: Asyncio stream reader.
        writer: Asyncio stream writer.
        config: TCP configuration.
    """

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    config: TcpConfig = field(default_factory=TcpConfig)

    _state: ChannelState = field(default=ChannelState.OPEN, init=False)
    _statistics: ChannelStatistics = field(default_factory=ChannelStatistics, init=False)

    def __post_init__(self) -> None:
        """Initialize channel state."""
        self._statistics.connect_count = 1

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
        """Get local address (host, port)."""
        try:
            sockname = self.writer.get_extra_info("sockname")
            if sockname:
                return (sockname[0], sockname[1])
        except (AttributeError, IndexError):
            pass
        return None

    @property
    def remote_address(self) -> tuple[str, int] | None:
        """Get remote address (host, port) of connected client."""
        try:
            peername = self.writer.get_extra_info("peername")
            if peername:
                return (peername[0], peername[1])
        except (AttributeError, IndexError):
            pass
        return None

    async def open(self) -> None:
        """Open is a no-op for server channels (already open)."""
        pass

    async def close(self) -> None:
        """Close the channel."""
        if self._state == ChannelState.CLOSED:
            return

        self._state = ChannelState.CLOSING

        try:
            self.writer.close()
            await self.writer.wait_closed()
        except (OSError, ConnectionError):
            pass

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
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Channel is not open")

        try:
            timeout = self.config.read_timeout if self.config.read_timeout > 0 else None
            data = await asyncio.wait_for(
                self.reader.read(max_bytes),
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
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Channel is not open")

        try:
            self.writer.write(data)
            timeout = self.config.write_timeout if self.config.write_timeout > 0 else None
            await asyncio.wait_for(
                self.writer.drain(),
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
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Channel is not open")

        try:
            timeout = self.config.read_timeout if self.config.read_timeout > 0 else None
            data = await asyncio.wait_for(
                self.reader.readexactly(num_bytes),
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


@dataclass
class TcpServer:
    """TCP server for DNP3 communication.

    Listens for incoming TCP connections and creates TcpServerChannel
    instances for each accepted connection.

    Attributes:
        config: Server configuration.
    """

    config: TcpServerConfig = field(default_factory=TcpServerConfig)

    _state: ChannelState = field(default=ChannelState.CLOSED, init=False)
    _server: asyncio.Server | None = field(default=None, init=False)
    _accept_queue: asyncio.Queue[TcpServerChannel] = field(default=None, init=False)  # type: ignore[arg-type]
    _connections: list[TcpServerChannel] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Initialize internal state."""
        self._accept_queue = asyncio.Queue()

    @property
    def state(self) -> ChannelState:
        """Get current server state."""
        return self._state

    @property
    def is_listening(self) -> bool:
        """Check if server is listening for connections."""
        return self._state == ChannelState.OPEN

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Get local address (host, port) if listening."""
        if self._server is not None and self._server.sockets:
            try:
                sockname = self._server.sockets[0].getsockname()
                return (sockname[0], sockname[1])
            except (AttributeError, IndexError):
                pass
        return None

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    async def start(self) -> None:
        """Start listening for connections.

        Raises:
            ChannelError: If server cannot start.
        """
        if self._state == ChannelState.OPEN:
            return

        self._state = ChannelState.OPENING

        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                host=self.config.host,
                port=self.config.port,
                backlog=self.config.backlog,
                reuse_address=self.config.reuse_address,
            )
            self._state = ChannelState.OPEN
        except OSError as e:
            self._state = ChannelState.CLOSED
            raise ChannelError(f"Failed to start server on {self.config.host}:{self.config.port}: {e}") from e

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming connection.

        Args:
            reader: Stream reader for the connection.
            writer: Stream writer for the connection.
        """
        # Check max connections
        if self.config.max_connections > 0 and len(self._connections) >= self.config.max_connections:
            writer.close()
            await writer.wait_closed()
            return

        # Configure socket options
        sock = writer.get_extra_info("socket")
        if sock is not None:
            self._configure_socket(sock)

        # Create server channel
        channel = TcpServerChannel(
            reader=reader,
            writer=writer,
            config=TcpConfig(
                host=self.config.host,
                port=self.config.port,
                read_timeout=self.config.read_timeout,
                write_timeout=self.config.write_timeout,
                nodelay=self.config.nodelay,
                keepalive=self.config.keepalive,
                keepalive_idle=self.config.keepalive_idle,
                keepalive_interval=self.config.keepalive_interval,
                keepalive_count=self.config.keepalive_count,
            ),
        )

        self._connections.append(channel)
        await self._accept_queue.put(channel)

    def _configure_socket(self, sock: socket.socket) -> None:
        """Configure socket options.

        Args:
            sock: Socket to configure.
        """
        if self.config.nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        if self.config.keepalive:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

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

    async def stop(self) -> None:
        """Stop listening and close all connections."""
        if self._state == ChannelState.CLOSED:
            return

        self._state = ChannelState.CLOSING

        # Close all connections
        for conn in self._connections:
            await conn.close()
        self._connections.clear()

        # Stop the server
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clear accept queue
        while not self._accept_queue.empty():
            try:
                self._accept_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._state = ChannelState.CLOSED

    async def accept(self) -> TcpServerChannel:
        """Accept an incoming connection.

        Returns:
            Channel for the accepted connection.

        Raises:
            ChannelClosedError: If server is not listening.
        """
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Server is not listening")

        return await self._accept_queue.get()

    def remove_connection(self, channel: TcpServerChannel) -> None:
        """Remove a connection from the tracked list.

        Args:
            channel: Channel to remove.
        """
        if channel in self._connections:
            self._connections.remove(channel)

    async def __aenter__(self) -> "TcpServer":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.stop()


async def serve(
    host: str = "127.0.0.1",
    port: int = 20000,
    config: TcpServerConfig | None = None,
) -> TcpServer:
    """Create and start a TCP server.

    Args:
        host: Host address to bind to.
        port: Port to listen on.
        config: Optional server configuration.

    Returns:
        Started TcpServer.

    Raises:
        ChannelError: If server cannot start.
    """
    if config is None:
        config = TcpServerConfig(host=host, port=port)
    else:
        config = TcpServerConfig(
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
            backlog=config.backlog,
            reuse_address=config.reuse_address,
            max_connections=config.max_connections,
        )

    server = TcpServer(config=config)
    await server.start()
    return server
