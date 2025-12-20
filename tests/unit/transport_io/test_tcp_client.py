"""Tests for TCP client channel."""

import asyncio

import pytest

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelConnectionError,
    ChannelState,
    ChannelTimeoutError,
    TcpConfig,
)
from dnp3.transport_io.tcp_client import TcpClientChannel, connect


class TestTcpClientChannel:
    """Tests for TcpClientChannel."""

    def test_initial_state_closed(self) -> None:
        """New channel starts in CLOSED state."""
        channel = TcpClientChannel()
        assert channel.state == ChannelState.CLOSED
        assert channel.is_open is False

    def test_default_config(self) -> None:
        """Default config has sensible values."""
        channel = TcpClientChannel()
        assert channel.config.host == "127.0.0.1"
        assert channel.config.port == 20000
        assert channel.config.nodelay is True
        assert channel.config.keepalive is True

    def test_custom_config(self) -> None:
        """Can use custom config."""
        config = TcpConfig(host="192.168.1.1", port=30000)
        channel = TcpClientChannel(config=config)
        assert channel.config.host == "192.168.1.1"
        assert channel.config.port == 30000

    def test_local_address_when_not_connected(self) -> None:
        """Local address is None when not connected."""
        channel = TcpClientChannel()
        assert channel.local_address is None

    def test_remote_address_when_not_connected(self) -> None:
        """Remote address is None when not connected."""
        channel = TcpClientChannel()
        assert channel.remote_address is None

    @pytest.mark.asyncio
    async def test_read_on_closed_raises(self) -> None:
        """Reading from closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.read(100)

    @pytest.mark.asyncio
    async def test_write_on_closed_raises(self) -> None:
        """Writing to closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.write(b"test")

    @pytest.mark.asyncio
    async def test_read_exactly_on_closed_raises(self) -> None:
        """read_exactly on closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self) -> None:
        """Closing already closed channel is no-op."""
        channel = TcpClientChannel()
        await channel.close()  # Should not raise
        assert channel.state == ChannelState.CLOSED


class TestTcpClientWithServer:
    """Tests for TCP client with real network operations."""

    @pytest.mark.asyncio
    async def test_connect_to_server(self) -> None:
        """Client can connect to server."""

        # Start a simple echo server
        async def echo_handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            echo_handler,
            host="127.0.0.1",
            port=0,  # Let OS choose port
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                assert channel.state == ChannelState.OPEN
                assert channel.is_open is True
                assert channel.local_address is not None
                assert channel.remote_address == ("127.0.0.1", port)
                assert channel.statistics.connect_count == 1

                await channel.close()
                assert channel.state == ChannelState.CLOSED
                assert channel.statistics.disconnect_count == 1
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_write_and_read(self) -> None:
        """Client can write and read data."""

        async def echo_handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            echo_handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write(b"hello")
                response = await channel.read(100)
                assert response == b"hello"

                assert channel.statistics.bytes_sent == 5
                assert channel.statistics.bytes_received == 5

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_exactly(self) -> None:
        """Client can read exact number of bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"12345")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                data = await channel.read_exactly(5)
                assert data == b"12345"

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_write_all(self) -> None:
        """write_all sends all data."""
        received: list[bytes] = []

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            data = await reader.read(1024)
            received.append(data)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write_all(b"complete message")
                await channel.close()

                # Wait for server to receive
                await asyncio.sleep(0.1)
                assert received[0] == b"complete message"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_exactly_eof(self) -> None:
        """read_exactly raises on EOF before requested bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"hi")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                with pytest.raises(ChannelClosedError, match="EOF"):
                    await channel.read_exactly(10)

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Channel works as async context manager."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                async with TcpClientChannel(config=config) as channel:
                    assert channel.is_open is True

                assert channel.is_open is False
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_helper(self) -> None:
        """connect() helper creates connected channel."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                channel = await connect("127.0.0.1", port)
                assert channel.is_open is True
                await channel.close()
        finally:
            server.close()
            await server.wait_closed()


class TestTcpClientErrors:
    """Tests for TCP client error handling."""

    @pytest.mark.asyncio
    async def test_connect_refused(self) -> None:
        """Connection refused raises appropriate error."""
        # Use a port that's likely not in use
        config = TcpConfig(host="127.0.0.1", port=59999)
        channel = TcpClientChannel(config=config)

        with pytest.raises(ChannelConnectionError):
            await channel.open()

        assert channel.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_connect_timeout(self) -> None:
        """Connection timeout raises appropriate error."""
        # Use a non-routable IP to cause timeout
        config = TcpConfig(
            host="10.255.255.1",  # Non-routable
            port=20000,
            connect_timeout=0.1,
        )
        channel = TcpClientChannel(config=config)

        with pytest.raises(ChannelTimeoutError):
            await channel.open()

        assert channel.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_read_eof(self) -> None:
        """Reading after server closes returns empty bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                # Wait for server handler to close
                await asyncio.sleep(0.1)

                data = await channel.read(100)
                assert data == b""  # EOF

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_timeout(self) -> None:
        """Read timeout raises appropriate error."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            await asyncio.sleep(10)  # Never send anything
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(
                    host="127.0.0.1",
                    port=port,
                    read_timeout=0.1,
                )
                channel = TcpClientChannel(config=config)
                await channel.open()

                with pytest.raises(ChannelTimeoutError):
                    await channel.read(100)

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()


class TestTcpClientStatistics:
    """Tests for TCP client statistics."""

    @pytest.mark.asyncio
    async def test_bytes_sent_tracking(self) -> None:
        """Bytes sent are tracked correctly."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            await reader.read(1024)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write(b"12345")
                await channel.write(b"67890")
                assert channel.statistics.bytes_sent == 10
                assert channel.statistics.messages_sent == 2

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_bytes_received_tracking(self) -> None:
        """Bytes received are tracked correctly."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"hello")
            await writer.drain()
            writer.write(b"world")
            await writer.drain()
            await asyncio.sleep(0.5)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.read(100)
                await channel.read(100)
                # Note: messages_received counts read operations, not network packets
                # bytes_received should be 10 total
                assert channel.statistics.bytes_received == 10

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()
