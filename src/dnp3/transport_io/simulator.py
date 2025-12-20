"""In-memory channel simulator for testing.

The simulator provides a pair of connected channels that can be used
to test master/outstation communication without actual network I/O.
"""

import asyncio
import contextlib
import random
from dataclasses import dataclass, field

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelError,
    ChannelState,
    ChannelStatistics,
    ChannelTimeoutError,
    SimulatorConfig,
)


@dataclass
class SimulatorChannel:
    """In-memory channel for testing.

    Provides async read/write operations backed by asyncio queues.
    Supports simulated latency, packet loss, and bandwidth limits.

    Attributes:
        config: Channel configuration.
        name: Optional name for debugging.
    """

    config: SimulatorConfig = field(default_factory=SimulatorConfig)
    name: str = ""

    _state: ChannelState = field(default=ChannelState.CLOSED, init=False)
    _statistics: ChannelStatistics = field(default_factory=ChannelStatistics, init=False)
    _read_queue: asyncio.Queue[bytes] = field(default=None, init=False)  # type: ignore[arg-type]
    _peer: "SimulatorChannel | None" = field(default=None, init=False)
    _read_buffer: bytes = field(default=b"", init=False)

    def __post_init__(self) -> None:
        """Initialize internal state."""
        self._read_queue = asyncio.Queue(maxsize=self.config.buffer_size)

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
    def peer(self) -> "SimulatorChannel | None":
        """Get the peer channel (other end of the connection)."""
        return self._peer

    async def open(self) -> None:
        """Open the channel.

        For simulator channels, this just transitions to OPEN state.
        Use connect() to connect to a peer channel.
        """
        if self._state == ChannelState.OPEN:
            return
        self._state = ChannelState.OPENING
        self._state = ChannelState.OPEN
        self._statistics.connect_count += 1

    async def close(self) -> None:
        """Close the channel and disconnect from peer."""
        if self._state == ChannelState.CLOSED:
            return

        self._state = ChannelState.CLOSING
        self._statistics.disconnect_count += 1

        # Disconnect from peer
        if self._peer is not None:
            peer = self._peer
            self._peer = None
            if peer._peer is self:
                peer._peer = None
                # Signal EOF to peer
                with contextlib.suppress(asyncio.QueueFull):
                    peer._read_queue.put_nowait(b"")

        # Clear read buffer
        self._read_buffer = b""
        while not self._read_queue.empty():
            try:
                self._read_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._state = ChannelState.CLOSED

    async def read(self, max_bytes: int) -> bytes:
        """Read up to max_bytes from the channel.

        Args:
            max_bytes: Maximum number of bytes to read.

        Returns:
            Bytes read. Empty bytes indicates EOF.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelTimeoutError: If read times out.
        """
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Channel is not open")

        # Return from buffer first
        if self._read_buffer:
            data = self._read_buffer[:max_bytes]
            self._read_buffer = self._read_buffer[max_bytes:]
            return data

        # Wait for data from queue
        timeout = self.config.read_timeout if self.config.read_timeout > 0 else None
        try:
            data = await asyncio.wait_for(self._read_queue.get(), timeout=timeout)
        except TimeoutError as e:
            raise ChannelTimeoutError("Read timed out") from e

        if not data:  # EOF
            return b""

        # Apply simulated latency
        if self.config.latency > 0:
            await asyncio.sleep(self.config.latency)

        # Return requested amount, buffer the rest
        if len(data) > max_bytes:
            self._read_buffer = data[max_bytes:]
            data = data[:max_bytes]

        self._statistics.bytes_received += len(data)
        self._statistics.messages_received += 1
        return data

    async def write(self, data: bytes) -> int:
        """Write data to the channel.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelError: If no peer connected or write fails.
        """
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Channel is not open")

        if self._peer is None:
            raise ChannelError("No peer connected")

        # Simulate packet loss
        if self.config.packet_loss > 0 and random.random() < self.config.packet_loss:
            self._statistics.bytes_sent += len(data)
            self._statistics.messages_sent += 1
            return len(data)  # Pretend we sent it

        # Apply simulated latency
        if self.config.latency > 0:
            await asyncio.sleep(self.config.latency)

        # Apply bandwidth limit
        if self.config.bandwidth_limit > 0:
            delay = len(data) / self.config.bandwidth_limit
            await asyncio.sleep(delay)

        # Send to peer's read queue
        try:
            self._peer._read_queue.put_nowait(data)
        except asyncio.QueueFull as e:
            raise ChannelError("Peer buffer full") from e

        self._statistics.bytes_sent += len(data)
        self._statistics.messages_sent += 1
        return len(data)

    async def read_exactly(self, num_bytes: int) -> bytes:
        """Read exactly num_bytes from the channel.

        Args:
            num_bytes: Exact number of bytes to read.

        Returns:
            Exactly num_bytes of data.

        Raises:
            ChannelClosedError: If channel is closed or EOF.
            ChannelTimeoutError: If read times out.
        """
        result = bytearray()
        while len(result) < num_bytes:
            chunk = await self.read(num_bytes - len(result))
            if not chunk:
                raise ChannelClosedError("EOF before reading requested bytes")
            result.extend(chunk)
        return bytes(result)

    async def write_all(self, data: bytes) -> None:
        """Write all data to the channel.

        Args:
            data: Bytes to write.

        Raises:
            ChannelClosedError: If channel is closed.
            ChannelError: If write fails.
        """
        written = await self.write(data)
        if written != len(data):
            raise ChannelError(f"Only wrote {written} of {len(data)} bytes")

    def connect_to(self, peer: "SimulatorChannel") -> None:
        """Connect this channel to a peer channel.

        Args:
            peer: The peer channel to connect to.

        Raises:
            ChannelError: If already connected to a different peer.
        """
        if self._peer is not None and self._peer is not peer:
            raise ChannelError("Already connected to a different peer")

        self._peer = peer
        peer._peer = self


def create_channel_pair(
    config: SimulatorConfig | None = None,
    config_a: SimulatorConfig | None = None,
    config_b: SimulatorConfig | None = None,
) -> tuple[SimulatorChannel, SimulatorChannel]:
    """Create a connected pair of simulator channels.

    Args:
        config: Shared config for both channels (if config_a/config_b not set).
        config_a: Config for channel A.
        config_b: Config for channel B.

    Returns:
        Tuple of (channel_a, channel_b) connected to each other.
    """
    if config is None:
        config = SimulatorConfig()

    channel_a = SimulatorChannel(
        config=config_a or config,
        name="channel_a",
    )
    channel_b = SimulatorChannel(
        config=config_b or config,
        name="channel_b",
    )

    channel_a.connect_to(channel_b)
    return channel_a, channel_b


@dataclass
class SimulatorServer:
    """In-memory server for testing.

    Accepts connections from SimulatorClient instances.

    Attributes:
        config: Server configuration.
        name: Optional name for debugging.
    """

    config: SimulatorConfig = field(default_factory=SimulatorConfig)
    name: str = "server"

    _state: ChannelState = field(default=ChannelState.CLOSED, init=False)
    _accept_queue: asyncio.Queue[SimulatorChannel] = field(default=None, init=False)  # type: ignore[arg-type]
    _connections: list[SimulatorChannel] = field(default_factory=list, init=False)

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
        """Get local address (simulated)."""
        if self._state == ChannelState.OPEN:
            return ("simulator", 0)
        return None

    @property
    def connection_count(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    async def start(self) -> None:
        """Start listening for connections."""
        if self._state == ChannelState.OPEN:
            return
        self._state = ChannelState.OPENING
        self._state = ChannelState.OPEN

    async def stop(self) -> None:
        """Stop listening and close all connections."""
        if self._state == ChannelState.CLOSED:
            return

        self._state = ChannelState.CLOSING

        # Close all connections
        for conn in self._connections:
            await conn.close()
        self._connections.clear()

        # Clear accept queue
        while not self._accept_queue.empty():
            try:
                self._accept_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._state = ChannelState.CLOSED

    async def accept(self) -> SimulatorChannel:
        """Accept an incoming connection.

        Returns:
            Channel for the accepted connection.

        Raises:
            ChannelClosedError: If server is stopped.
        """
        if self._state != ChannelState.OPEN:
            raise ChannelClosedError("Server is not listening")

        channel = await self._accept_queue.get()
        self._connections.append(channel)
        return channel

    def _queue_connection(self, client_channel: SimulatorChannel) -> SimulatorChannel:
        """Internal: Queue a client connection for acceptance.

        Args:
            client_channel: The client-side channel.

        Returns:
            The server-side channel.

        Raises:
            ChannelError: If server is not listening.
        """
        if self._state != ChannelState.OPEN:
            raise ChannelError("Server is not listening")

        server_channel = SimulatorChannel(
            config=self.config,
            name=f"{self.name}_conn_{len(self._connections)}",
        )
        server_channel.connect_to(client_channel)
        self._accept_queue.put_nowait(server_channel)
        return server_channel


@dataclass
class SimulatorClient:
    """In-memory client for testing.

    Connects to SimulatorServer instances.

    Attributes:
        config: Client configuration.
        name: Optional name for debugging.
    """

    config: SimulatorConfig = field(default_factory=SimulatorConfig)
    name: str = "client"

    _channel: SimulatorChannel | None = field(default=None, init=False)

    @property
    def channel(self) -> SimulatorChannel | None:
        """Get the connected channel."""
        return self._channel

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._channel is not None and self._channel.is_open

    async def connect(self, server: SimulatorServer) -> SimulatorChannel:
        """Connect to a simulator server.

        Args:
            server: The server to connect to.

        Returns:
            The connected channel.

        Raises:
            ChannelError: If connection fails.
        """
        if self._channel is not None:
            await self._channel.close()

        self._channel = SimulatorChannel(
            config=self.config,
            name=self.name,
        )
        server._queue_connection(self._channel)
        await self._channel.open()
        return self._channel

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
