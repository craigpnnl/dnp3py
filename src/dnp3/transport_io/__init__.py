"""DNP3 I/O Layer.

This module provides transport I/O abstractions for DNP3 communication,
including TCP client/server implementations and an in-memory simulator
for testing.
"""

from dnp3.transport_io.channel import (
    Channel,
    ChannelClosedError,
    ChannelConfig,
    ChannelConnectionError,
    ChannelError,
    ChannelState,
    ChannelStatistics,
    ChannelTimeoutError,
    ServerChannel,
    SimulatorConfig,
    TcpConfig,
    TcpServerConfig,
)
from dnp3.transport_io.simulator import (
    SimulatorChannel,
    SimulatorClient,
    SimulatorServer,
    create_channel_pair,
)
from dnp3.transport_io.tcp_client import TcpClientChannel, connect
from dnp3.transport_io.tcp_server import TcpServer, TcpServerChannel, serve

__all__ = [
    # Channel protocols and base types
    "Channel",
    "ChannelClosedError",
    "ChannelConfig",
    "ChannelConnectionError",
    "ChannelError",
    "ChannelState",
    "ChannelStatistics",
    "ChannelTimeoutError",
    "ServerChannel",
    # Simulator types
    "SimulatorChannel",
    "SimulatorClient",
    "SimulatorConfig",
    "SimulatorServer",
    # TCP types
    "TcpClientChannel",
    "TcpConfig",
    "TcpServer",
    "TcpServerChannel",
    "TcpServerConfig",
    "connect",
    "create_channel_pair",
    "serve",
]
