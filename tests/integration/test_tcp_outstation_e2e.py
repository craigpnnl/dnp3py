"""Integration tests for OutstationTcpRunner over real TCP.

Tests the full stack end-to-end: TCP connection, data link framing,
transport reassembly, application processing, and response.
"""

import asyncio
import contextlib

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.application.parser import parse_response
from dnp3.core.enums import FunctionCode, LinkFunctionCode
from dnp3.core.flags import BinaryQuality
from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database, EventClass
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.parser import FrameParser
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner
from dnp3.transport.segment import TransportSegment

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


class TestTcpOutstationE2E:
    """End-to-end tests with real TCP connections."""

    @pytest.mark.asyncio
    async def test_connect_reset_integrity_poll(self) -> None:
        """Start runner on port 0, connect client, send reset + integrity poll, verify response."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)

        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
        outstation = Outstation(config=config, database=database)
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)

        # Start runner
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)  # let it bind

        assert runner.is_running
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        try:
            # Connect as client
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

            # Send integrity poll
            request = build_integrity_poll(seq=0)
            frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
            writer.write(frame_bytes)
            await writer.drain()

            # Read response
            resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            resp_frames = list(parser.feed(resp_data))
            assert len(resp_frames) >= 1

            resp_frame = resp_frames[0]
            assert resp_frame.user_data
            segment = TransportSegment.from_bytes(resp_frame.user_data)
            response = parse_response(segment.payload)
            assert response.header.function == FunctionCode.RESPONSE

            writer.close()
            await writer.wait_closed()
        finally:
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task

    @pytest.mark.asyncio
    async def test_outstation_with_multiple_point_types(self) -> None:
        """Outstation with binary + analog inputs, integrity poll returns data."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.update_analog_input(0, value=42.5)

        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
        outstation = Outstation(config=config, database=database)
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)

        addr = runner.local_address
        assert addr is not None
        host, port = addr

        try:
            reader, writer = await asyncio.open_connection(host, port)

            # Send integrity poll directly (no reset needed for unconfirmed)
            request = build_integrity_poll(seq=0)
            frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
            writer.write(frame_bytes)
            await writer.drain()

            # Read response
            parser = FrameParser()
            resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            resp_frames = list(parser.feed(resp_data))
            assert len(resp_frames) >= 1

            resp_frame = resp_frames[0]
            assert resp_frame.user_data
            segment = TransportSegment.from_bytes(resp_frame.user_data)
            response = parse_response(segment.payload)
            assert response.header.function == FunctionCode.RESPONSE
            # Should have object blocks for the points
            assert len(response.objects) > 0

            writer.close()
            await writer.wait_closed()
        finally:
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task
