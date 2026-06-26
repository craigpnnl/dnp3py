"""TCP transport runner for DNP3 outstations."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from dnp3.core.enums import LinkFunctionCode
from dnp3.datalink.builder import build_ack, build_link_status, build_unconfirmed_user_data
from dnp3.datalink.parser import FrameParser
from dnp3.outstation.outstation import Outstation
from dnp3.transport.reassembler import Reassembler
from dnp3.transport.segment import TransportSegment
from dnp3.transport.segmenter import Segmenter
from dnp3.transport_io.channel import ChannelClosedError, ChannelError
from dnp3.transport_io.tcp_server import TcpServer, TcpServerChannel, serve

logger = logging.getLogger(__name__)


@dataclass
class OutstationTcpRunner:
    """Runs an outstation over TCP, handling full protocol stack."""

    outstation: Outstation
    host: str = "0.0.0.0"
    port: int = 20000

    _server: TcpServer | None = field(default=None, init=False, repr=False)
    _shutdown: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _connection_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    @property
    def is_running(self) -> bool:
        """Check if the TCP server is running."""
        return self._server is not None and self._server.is_listening

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Get the local address the server is bound to."""
        if self._server is not None:
            return self._server.local_address
        return None

    async def run(self) -> None:
        """Start the TCP server and accept connections until stopped."""
        self._shutdown.clear()
        self._server = await serve(self.host, self.port)
        logger.info("Outstation TCP server listening on %s:%d", self.host, self.port)

        try:
            while not self._shutdown.is_set():
                try:
                    channel = await asyncio.wait_for(
                        self._server.accept(),
                        timeout=1.0,
                    )
                except TimeoutError:
                    continue
                except ChannelClosedError:
                    break

                # Close any existing connection (DNP3 TCP is point-to-point)
                if self._connection_task is not None and not self._connection_task.done():
                    self._connection_task.cancel()
                    try:
                        await self._connection_task
                    except (asyncio.CancelledError, Exception):
                        pass

                logger.info("Accepted connection")
                self._connection_task = asyncio.create_task(self._handle_connection(channel))
        finally:
            if self._connection_task is not None and not self._connection_task.done():
                self._connection_task.cancel()
                try:
                    await self._connection_task
                except (asyncio.CancelledError, Exception):
                    pass
            await self._server.stop()

    async def stop(self) -> None:
        """Signal shutdown and stop the server."""
        self._shutdown.set()
        if self._server is not None:
            await self._server.stop()

    async def _handle_connection(self, channel: TcpServerChannel | object) -> None:
        """Handle a single client connection through the full protocol stack.

        Args:
            channel: A channel with read/write_all/close async methods.
                     Typically TcpServerChannel, but can be SimulatorChannel for testing.
        """
        parser = FrameParser()
        # Bound the reassembler to the outstation's configured fragment cap so a
        # never-FIN transport stream cannot exhaust process memory.
        # ReassemblyError propagates to the outer except-Exception handler which
        # logs and closes the connection (fails closed).
        reassembler = Reassembler(max_fragment_size=self.outstation.config.max_fragment_size)
        segmenter = Segmenter()
        outstation_addr = self.outstation.config.address
        master_addr = self.outstation.config.master_address  # 0 = learn from first frame
        learned_master_addr = 0

        try:
            while not self._shutdown.is_set():
                data = await channel.read(4096)  # type: ignore[union-attr]
                if not data:
                    break  # EOF

                for frame in parser.feed(data):
                    # Address check: frame destination must match our address
                    if frame.header.destination != outstation_addr:
                        continue

                    # Learn master address from first frame if not configured
                    if learned_master_addr == 0:
                        learned_master_addr = frame.header.source

                    effective_master = master_addr if master_addr != 0 else learned_master_addr

                    # Only process primary frames (from master)
                    if not frame.header.control.prm:
                        continue

                    fc = frame.header.control.function_code

                    # Link-layer management
                    if fc == LinkFunctionCode.PRI_RESET_LINK_STATE:
                        ack = build_ack(effective_master, outstation_addr, False)
                        await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                        continue

                    if fc == LinkFunctionCode.PRI_REQUEST_LINK_STATUS:
                        status = build_link_status(effective_master, outstation_addr, False)
                        await channel.write_all(status.to_bytes())  # type: ignore[union-attr]
                        continue

                    if fc == LinkFunctionCode.PRI_TEST_LINK_STATE:
                        ack = build_ack(effective_master, outstation_addr, False)
                        await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                        continue

                    if fc == LinkFunctionCode.PRI_CONFIRMED_USER_DATA:
                        # ACK the confirmed data
                        ack = build_ack(effective_master, outstation_addr, False)
                        await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                        # Fall through to process user data
                    elif fc == LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA:
                        pass  # Fall through to process user data
                    else:
                        continue  # Unsupported function code

                    # Extract transport segment from user data
                    if not frame.user_data:
                        continue

                    segment = TransportSegment.from_bytes(frame.user_data)
                    result = reassembler.add(segment)

                    if result is not None:
                        # Complete application fragment received
                        responses = self.outstation.process_request(result.data)
                        is_multi = len(responses) > 1

                        for i, response in enumerate(responses):
                            is_last_fragment = i == len(responses) - 1

                            # For non-final fragments in multi-fragment responses,
                            # set the CON bit to request application-layer confirm
                            if is_multi and not is_last_fragment:
                                resp_bytes = bytearray(response.to_bytes())
                                resp_bytes[0] |= 0x20  # Set CON bit (bit 5)
                                resp_bytes = bytes(resp_bytes)
                            else:
                                resp_bytes = response.to_bytes()

                            segments = segmenter.segment(resp_bytes)

                            for seg in segments:
                                resp_frame = build_unconfirmed_user_data(
                                    destination=effective_master,
                                    source=outstation_addr,
                                    dir_from_master=False,
                                    user_data=seg.to_bytes(),
                                )
                                await channel.write_all(resp_frame.to_bytes())  # type: ignore[union-attr]

                            # Wait for APPLICATION_CONFIRM before sending next fragment
                            if is_multi and not is_last_fragment:
                                confirm_received = await self._wait_for_confirm(
                                    channel,
                                    parser,
                                    reassembler,
                                    outstation_addr,
                                    effective_master,
                                    timeout=self.outstation.config.confirm_timeout,
                                )
                                if not confirm_received:
                                    logger.warning(
                                        "Timed out waiting for application confirm after fragment %d of %d",
                                        i + 1,
                                        len(responses),
                                    )
                                    break
        except (ChannelClosedError, asyncio.CancelledError):
            pass
        except ChannelError as exc:
            # Transport error on an established connection: log so it is
            # distinguishable from a normal peer-initiated close.
            logger.warning("Transport channel error: %s", exc)
        except Exception:
            logger.exception("Error handling connection")
        finally:
            try:
                await channel.close()  # type: ignore[union-attr]
            except Exception:
                pass
            logger.info("Connection closed")

    async def _wait_for_confirm(
        self,
        channel: TcpServerChannel | object,
        parser: FrameParser,
        reassembler: Reassembler,
        outstation_addr: int,
        master_addr: int,
        timeout: float = 5.0,
    ) -> bool:
        """Wait for an APPLICATION_CONFIRM from the master.

        Per IEEE 1815-2012, after sending a non-final fragment with CON=1,
        the outstation must wait for the master to send a CONFIRM (FC 0x00)
        before transmitting the next fragment.

        Args:
            channel: Communication channel.
            parser: Frame parser instance.
            reassembler: Transport reassembler (a fresh one is used internally).
            outstation_addr: This outstation's address.
            master_addr: The master's address.
            timeout: Maximum seconds to wait for confirm.

        Returns:
            True if confirm received, False on timeout or error.
        """
        # Mirror the connection reassembler's cap so confirm frames are bounded
        # by the same config value that governs all other reassembly.
        confirm_reassembler = Reassembler(max_fragment_size=self.outstation.config.max_fragment_size)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False

            try:
                data = await asyncio.wait_for(
                    channel.read(4096),  # type: ignore[union-attr]
                    timeout=remaining,
                )
            except TimeoutError:
                return False

            if not data:
                return False

            for frame in parser.feed(data):
                if frame.header.destination != outstation_addr:
                    continue
                if not frame.header.control.prm:
                    continue

                fc = frame.header.control.function_code

                # Handle link-layer management frames that might arrive
                if fc == LinkFunctionCode.PRI_RESET_LINK_STATE:
                    ack = build_ack(master_addr, outstation_addr, False)
                    await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                    continue

                if fc == LinkFunctionCode.PRI_REQUEST_LINK_STATUS:
                    status = build_link_status(master_addr, outstation_addr, False)
                    await channel.write_all(status.to_bytes())  # type: ignore[union-attr]
                    continue

                if fc == LinkFunctionCode.PRI_TEST_LINK_STATE:
                    ack = build_ack(master_addr, outstation_addr, False)
                    await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                    continue

                if fc == LinkFunctionCode.PRI_CONFIRMED_USER_DATA:
                    ack = build_ack(master_addr, outstation_addr, False)
                    await channel.write_all(ack.to_bytes())  # type: ignore[union-attr]
                    # Fall through to process user data
                elif fc == LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA:
                    pass  # Fall through to process user data
                else:
                    continue

                if not frame.user_data:
                    continue

                segment = TransportSegment.from_bytes(frame.user_data)
                result = confirm_reassembler.add(segment)

                if result is not None and len(result.data) >= 2:
                    # Check function code (second byte of application data)
                    func_code = result.data[1]
                    if func_code == 0x00:  # FunctionCode.CONFIRM
                        return True

        return False
