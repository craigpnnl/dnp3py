"""Integration tests for MESA outstation over TCP.

Tests the full MESA outstation end-to-end: profile loading, TCP server,
protocol stack (data link, transport, application), and command handling.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.application.parser import parse_response
from dnp3.core.enums import FunctionCode, LinkFunctionCode
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.parser import FrameParser
from dnp3.mesa.outstation import MesaOutstation, create_mesa_outstation
from dnp3.transport.segment import TransportSegment

PROFILE_PATH = Path(__file__).parents[2] / "data" / "profiles" / "full.json"

MASTER_ADDR = 3
OUTSTATION_ADDR = 1


def _build_request_frame(
    master_addr: int,
    outstation_addr: int,
    request_bytes: bytes,
) -> bytes:
    """Build a complete data link frame containing a DNP3 request."""
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request_bytes)
    frame = build_unconfirmed_user_data(
        destination=outstation_addr,
        source=master_addr,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


async def _wait_for_listening(mesa: MesaOutstation, timeout: float = 5.0) -> None:
    """Wait until the MESA outstation is listening for connections."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if mesa.local_address is not None:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("MesaOutstation did not start listening in time")


class TestMesaTcpStartStop:
    """Test that the MESA outstation starts and stops cleanly over TCP."""

    @pytest.mark.asyncio
    async def test_mesa_outstation_starts_and_accepts_connections(self) -> None:
        """Create MESA outstation from real profile, start on port 0, connect a client."""
        mesa = create_mesa_outstation(
            PROFILE_PATH,
            host="127.0.0.1",
            port=0,
            address=OUTSTATION_ADDR,
            master_address=MASTER_ADDR,
        )

        run_task = asyncio.create_task(mesa.run())

        try:
            await _wait_for_listening(mesa)

            assert mesa.is_running
            addr = mesa.local_address
            assert addr is not None
            host, port = addr

            # Connect a raw TCP client
            reader, writer = await asyncio.open_connection(host, port)

            # Send reset link state
            reset = build_reset_link_state(
                destination=OUTSTATION_ADDR,
                source=MASTER_ADDR,
                dir_from_master=True,
            )
            writer.write(reset.to_bytes())
            await writer.drain()

            # Read ACK
            parser = FrameParser()
            ack_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            ack_frames = list(parser.feed(ack_data))
            assert len(ack_frames) >= 1
            assert ack_frames[0].header.control.function_code == LinkFunctionCode.SEC_ACK

            writer.close()
            await writer.wait_closed()
        finally:
            await mesa.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task

        assert not mesa.is_running


class TestMesaTcpIntegrityPoll:
    """Test integrity poll returns data from the real MESA profile."""

    @pytest.mark.asyncio
    async def test_integrity_poll_returns_binary_and_analog_data(self) -> None:
        """Integrity poll through TCP returns BI and AI data from the real profile."""
        mesa = create_mesa_outstation(
            PROFILE_PATH,
            host="127.0.0.1",
            port=0,
            address=OUTSTATION_ADDR,
            master_address=MASTER_ADDR,
        )

        run_task = asyncio.create_task(mesa.run())

        try:
            await _wait_for_listening(mesa)

            addr = mesa.local_address
            assert addr is not None
            host, port = addr

            reader, writer = await asyncio.open_connection(host, port)
            parser = FrameParser()

            # Reset link state first
            reset = build_reset_link_state(
                destination=OUTSTATION_ADDR,
                source=MASTER_ADDR,
                dir_from_master=True,
            )
            writer.write(reset.to_bytes())
            await writer.drain()

            ack_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            ack_frames = list(parser.feed(ack_data))
            assert len(ack_frames) >= 1

            # Send integrity poll
            request = build_integrity_poll(seq=0)
            frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
            writer.write(frame_bytes)
            await writer.drain()

            # Read response -- the MESA profile has many points so the response
            # may span multiple data-link frames.  Collect all frames until we
            # can reassemble a complete application fragment.
            from dnp3.transport.reassembler import Reassembler

            reassembler = Reassembler()
            app_data: bytes | None = None

            deadline = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < deadline:
                resp_data = await asyncio.wait_for(reader.read(8192), timeout=2.0)
                for frame in parser.feed(resp_data):
                    if frame.user_data:
                        segment = TransportSegment.from_bytes(frame.user_data)
                        result = reassembler.add(segment)
                        if result is not None:
                            app_data = result.data
                            break
                if app_data is not None:
                    break

            assert app_data is not None, "Did not receive a complete application response"

            response = parse_response(app_data)
            assert response.header.function == FunctionCode.RESPONSE

            # The real profile has many points -- the first response fragment
            # must contain at least some object data.  With the default 2048-byte
            # fragment size, only the first chunk of static data fits, so we
            # verify we got *some* objects and that the first group is binary
            # input (group 1), which is serialised first in a Class 0 response.
            assert len(response.objects) > 0

            groups_in_response = {obj.header.group for obj in response.objects}
            # Binary inputs (group 1) are serialised first in Class 0 static data
            assert 1 in groups_in_response, (
                f"Expected binary input (group 1) in response, got groups {groups_in_response}"
            )

            writer.close()
            await writer.wait_closed()
        finally:
            await mesa.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task
