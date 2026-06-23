"""Unit tests for OutstationTcpRunner connection handling.

Tests the protocol stack integration by calling _handle_connection()
directly with SimulatorChannel pairs, bypassing real TCP.
"""

import asyncio

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.application.header import ApplicationControl
from dnp3.core.enums import FunctionCode, LinkFunctionCode
from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    Database,
    DatabaseConfig,
    EventClass,
)
from dnp3.datalink.builder import (
    build_confirmed_user_data,
    build_request_link_status,
    build_reset_link_state,
    build_unconfirmed_user_data,
)
from dnp3.datalink.parser import FrameParser
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.tcp_runner import OutstationTcpRunner
from dnp3.transport.reassembler import Reassembler
from dnp3.transport.segment import TransportSegment
from dnp3.transport_io.simulator import SimulatorChannel, create_channel_pair

MASTER_ADDR = 3
OUTSTATION_ADDR = 1


def _make_outstation(
    address: int = OUTSTATION_ADDR,
    master_address: int = MASTER_ADDR,
    database: Database | None = None,
) -> Outstation:
    """Create an outstation with a simple config."""
    config = OutstationConfig(address=address, master_address=master_address)
    if database is None:
        database = Database()
    return Outstation(config=config, database=database)


def _make_runner(outstation: Outstation) -> OutstationTcpRunner:
    """Create a runner (won't call run(), just _handle_connection)."""
    return OutstationTcpRunner(outstation=outstation)


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


async def _read_response_frame(channel: SimulatorChannel, timeout: float = 2.0):
    """Read a complete data link frame from the channel."""
    data = b""
    deadline = asyncio.get_event_loop().time() + timeout
    parser = FrameParser()

    while asyncio.get_event_loop().time() < deadline:
        try:
            chunk = await asyncio.wait_for(channel.read(4096), timeout=0.5)
        except Exception:
            break
        if not chunk:
            break
        data += chunk
        frames = list(parser.feed(chunk))
        if frames:
            return frames[0]

    return None


class TestLinkResetHandshake:
    """Test link-layer reset handshake."""

    @pytest.mark.asyncio
    async def test_reset_link_state_returns_ack(self) -> None:
        """Send reset_link_state frame, verify ACK response."""
        outstation = _make_outstation()
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        # Send reset link state from master
        reset_frame = build_reset_link_state(
            destination=OUTSTATION_ADDR,
            source=MASTER_ADDR,
            dir_from_master=True,
        )
        await master_ch.write_all(reset_frame.to_bytes())

        # Run handler in background
        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Read response
        resp = await _read_response_frame(master_ch)
        assert resp is not None, "Expected ACK response"
        assert resp.header.control.function_code == LinkFunctionCode.SEC_ACK
        assert not resp.header.control.prm  # secondary frame
        assert resp.header.destination == MASTER_ADDR
        assert resp.header.source == OUTSTATION_ADDR

        # Clean up
        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestRequestLinkStatus:
    """Test link status request handling."""

    @pytest.mark.asyncio
    async def test_request_link_status_returns_link_status(self) -> None:
        """Send request_link_status, verify link_status response."""
        outstation = _make_outstation()
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        req_frame = build_request_link_status(
            destination=OUTSTATION_ADDR,
            source=MASTER_ADDR,
            dir_from_master=True,
        )
        await master_ch.write_all(req_frame.to_bytes())

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        resp = await _read_response_frame(master_ch)
        assert resp is not None, "Expected link status response"
        assert resp.header.control.function_code == LinkFunctionCode.SEC_LINK_STATUS
        assert not resp.header.control.prm
        assert resp.header.destination == MASTER_ADDR

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestSimpleReadRequest:
    """Test full protocol stack: integrity poll through all layers."""

    @pytest.mark.asyncio
    async def test_integrity_poll_returns_response(self) -> None:
        """Send integrity poll, verify we get an application response back."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)

        outstation = _make_outstation(database=database)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        # Build integrity poll request
        request = build_integrity_poll(seq=0)
        request_bytes = request.to_bytes()
        frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request_bytes)

        await master_ch.write_all(frame_bytes)

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Read the response frame
        resp_frame = await _read_response_frame(master_ch)
        assert resp_frame is not None, "Expected response frame"

        # Parse transport segment from response
        assert resp_frame.user_data, "Response should have user data"
        segment = TransportSegment.from_bytes(resp_frame.user_data)
        assert segment.is_first and segment.is_final, "Expected single segment response"

        # Parse application layer - should be a RESPONSE
        from dnp3.application.parser import parse_response

        response = parse_response(segment.payload)
        assert response.header.function == FunctionCode.RESPONSE

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestAddressFiltering:
    """Test that frames with wrong destination are ignored."""

    @pytest.mark.asyncio
    async def test_wrong_destination_ignored(self) -> None:
        """Send frame with wrong destination, verify no response."""
        outstation = _make_outstation()
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        # Send reset to wrong address
        wrong_frame = build_reset_link_state(
            destination=99,  # wrong address
            source=MASTER_ADDR,
            dir_from_master=True,
        )
        await master_ch.write_all(wrong_frame.to_bytes())

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Try to read - should time out with no response
        resp = await _read_response_frame(master_ch, timeout=0.5)
        assert resp is None, "Should not get response for wrong destination"

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestConfirmedData:
    """Test confirmed user data handling."""

    @pytest.mark.asyncio
    async def test_confirmed_data_gets_ack_then_response(self) -> None:
        """Send confirmed_user_data, verify ACK then application response."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig())
        database.update_binary_input(0, value=True)

        outstation = _make_outstation(database=database)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        # Build integrity poll as confirmed user data
        request = build_integrity_poll(seq=0)
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request.to_bytes())
        confirmed_frame = build_confirmed_user_data(
            destination=OUTSTATION_ADDR,
            source=MASTER_ADDR,
            dir_from_master=True,
            fcb=True,
            user_data=segment.to_bytes(),
        )
        await master_ch.write_all(confirmed_frame.to_bytes())

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # First response should be ACK
        ack_frame = await _read_response_frame(master_ch)
        assert ack_frame is not None, "Expected ACK"
        assert ack_frame.header.control.function_code == LinkFunctionCode.SEC_ACK

        # Second response should be the application response
        resp_frame = await _read_response_frame(master_ch)
        assert resp_frame is not None, "Expected application response"
        assert resp_frame.user_data, "Response should have user data"

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class TestConnectionClose:
    """Test clean connection close handling."""

    @pytest.mark.asyncio
    async def test_handler_exits_on_channel_close(self) -> None:
        """Close the channel, verify handler exits cleanly."""
        outstation = _make_outstation()
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Close master side -> EOF on outstation side
        await master_ch.close()

        # Handler should exit within a reasonable time
        await asyncio.wait_for(task, timeout=2.0)
        # If we get here without TimeoutError, handler exited cleanly


class TestMasterAddressLearning:
    """Test master address learning when configured as 0."""

    @pytest.mark.asyncio
    async def test_learns_master_address_from_first_frame(self) -> None:
        """With master_address=0, learn from first frame's source."""
        outstation = _make_outstation(master_address=0)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        # Send reset from address 42
        reset_frame = build_reset_link_state(
            destination=OUTSTATION_ADDR,
            source=42,
            dir_from_master=True,
        )
        await master_ch.write_all(reset_frame.to_bytes())

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Response should be addressed to 42 (learned)
        resp = await _read_response_frame(master_ch)
        assert resp is not None, "Expected ACK"
        assert resp.header.destination == 42, "Response should go to learned master address"

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _build_large_database(num_analog: int = 500) -> Database:
    """Create a database with enough analog inputs to force multi-fragment response.

    Each analog input (Group 30, Variation 1) is ~5 bytes of object data.
    With 500 points and a 249-byte max fragment, this produces multiple fragments.
    """
    config = DatabaseConfig(max_analog_inputs=num_analog)
    db = Database(config=config)
    for i in range(num_analog):
        db.add_analog_input(
            i,
            config=AnalogInputConfig(event_class=EventClass.CLASS_1),
            value=float(i),
            quality=AnalogQuality.ONLINE,
        )
    return db


def _build_confirm_frame(
    seq: int,
    master_addr: int,
    outstation_addr: int,
) -> bytes:
    """Build a complete datalink frame containing an APPLICATION_CONFIRM.

    APPLICATION_CONFIRM is a 2-byte application message:
      - Application control: FIR=1, FIN=1, CON=0, UNS=0, SEQ=<seq>
      - Function code: 0x00 (CONFIRM)
    """
    ac = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=seq)
    confirm_bytes = bytes([ac.to_byte(), FunctionCode.CONFIRM])
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=confirm_bytes)
    frame = build_unconfirmed_user_data(
        destination=outstation_addr,
        source=master_addr,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


async def _read_all_response_frames(
    channel: SimulatorChannel,
    timeout: float = 2.0,
) -> list:
    """Read all available response frames from a channel until timeout."""
    frames = []
    parser = FrameParser()
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            chunk = await asyncio.wait_for(channel.read(4096), timeout=min(remaining, 0.5))
        except (TimeoutError, Exception):
            break
        if not chunk:
            break
        for frame in parser.feed(chunk):
            frames.append(frame)

    return frames


async def _reassemble_fragment(
    channel: SimulatorChannel,
    reassembler: Reassembler,
    timeout: float = 3.0,
):
    """Read frames from channel until a complete application fragment is reassembled.

    Returns (fragment_bytes, app_control_byte) or (None, None) on timeout.
    """
    parser = FrameParser()
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        remaining = deadline - asyncio.get_event_loop().time()
        try:
            chunk = await asyncio.wait_for(channel.read(4096), timeout=min(remaining, 0.5))
        except (TimeoutError, Exception):
            break
        if not chunk:
            break

        for frame in parser.feed(chunk):
            if not frame.user_data:
                continue
            segment = TransportSegment.from_bytes(frame.user_data)
            result = reassembler.add(segment)
            if result is not None:
                # First byte of fragment data is the application control byte
                ac = ApplicationControl.from_byte(result.data[0])
                return result.data, ac

    return None, None


class TestMultiFragmentResponse:
    """Test multi-fragment response protocol with APPLICATION_CONFIRM handshake."""

    @pytest.mark.asyncio
    async def test_single_fragment_response_no_confirm_needed(self) -> None:
        """Small database integrity poll produces 1 fragment, no CON bit, no confirm wait."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)

        outstation = _make_outstation(database=database)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        request = build_integrity_poll(seq=0)
        frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
        await master_ch.write_all(frame_bytes)

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        reassembler = Reassembler()
        frag_data, ac = await _reassemble_fragment(master_ch, reassembler)
        assert frag_data is not None, "Expected a response fragment"
        assert ac.fir, "Single fragment should have FIR set"
        assert ac.fin, "Single fragment should have FIN set"
        assert not ac.con, "Single fragment should NOT have CON bit set"

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_multi_fragment_response_waits_for_confirm(self) -> None:
        """Large database integrity poll produces multiple fragments with CON handshake.

        The outstation must:
        1. Send fragment 1 with FIR=1, FIN=0, CON=1
        2. Wait for APPLICATION_CONFIRM from master
        3. Send fragment 2 (and so on)
        4. Final fragment has FIN=1, CON=0
        """
        database = _build_large_database(num_analog=500)
        config = OutstationConfig(
            address=OUTSTATION_ADDR,
            master_address=MASTER_ADDR,
            max_fragment_size=249,  # Force many fragments
        )
        outstation = Outstation(config=config, database=database)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        request = build_integrity_poll(seq=0)
        frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
        await master_ch.write_all(frame_bytes)

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        fragments_received = []
        reassembler = Reassembler()

        # Read first fragment - should have FIR=1, FIN=0, CON=1
        frag_data, ac = await _reassemble_fragment(master_ch, reassembler, timeout=3.0)
        assert frag_data is not None, "Expected first fragment"
        assert ac.fir, "First fragment should have FIR"
        assert not ac.fin, "First fragment should NOT have FIN (multi-fragment)"
        assert ac.con, "First fragment should have CON bit set to request confirm"
        fragments_received.append((frag_data, ac))

        # Send APPLICATION_CONFIRM matching the sequence
        confirm_frame = _build_confirm_frame(ac.seq, MASTER_ADDR, OUTSTATION_ADDR)
        await master_ch.write_all(confirm_frame)

        # Read remaining fragments, confirming each non-final one
        for _ in range(50):  # safety limit
            reassembler_next = Reassembler()
            frag_data, ac = await _reassemble_fragment(
                master_ch,
                reassembler_next,
                timeout=3.0,
            )
            if frag_data is None:
                break
            fragments_received.append((frag_data, ac))

            if ac.fin:
                # Final fragment should NOT have CON
                assert not ac.con, "Final fragment should not request confirm"
                break

            # Non-final fragment should have CON
            assert ac.con, "Non-final fragment should have CON bit"
            assert not ac.fir, "Middle fragments should not have FIR"

            # Send confirm for this fragment
            confirm_frame = _build_confirm_frame(ac.seq, MASTER_ADDR, OUTSTATION_ADDR)
            await master_ch.write_all(confirm_frame)

        assert len(fragments_received) >= 2, f"Expected multiple fragments, got {len(fragments_received)}"
        # First fragment: FIR=1, FIN=0
        assert fragments_received[0][1].fir
        assert not fragments_received[0][1].fin
        # Last fragment: FIR=0, FIN=1
        assert not fragments_received[-1][1].fir
        assert fragments_received[-1][1].fin

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    @pytest.mark.asyncio
    async def test_multi_fragment_timeout_on_no_confirm(self) -> None:
        """If master doesn't send confirm, outstation stops after timeout."""
        database = _build_large_database(num_analog=500)
        config = OutstationConfig(
            address=OUTSTATION_ADDR,
            master_address=MASTER_ADDR,
            max_fragment_size=249,
        )
        outstation = Outstation(config=config, database=database)
        runner = _make_runner(outstation)
        master_ch, outstation_ch = create_channel_pair()
        await master_ch.open()
        await outstation_ch.open()

        request = build_integrity_poll(seq=0)
        frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
        await master_ch.write_all(frame_bytes)

        task = asyncio.create_task(runner._handle_connection(outstation_ch))

        # Read first fragment
        reassembler = Reassembler()
        frag_data, ac = await _reassemble_fragment(master_ch, reassembler, timeout=3.0)
        assert frag_data is not None, "Expected first fragment"
        assert ac.con, "First fragment should have CON bit"

        # Do NOT send confirm - wait and verify no more fragments arrive
        reassembler2 = Reassembler()
        frag_data2, ac2 = await _reassemble_fragment(master_ch, reassembler2, timeout=3.0)
        assert frag_data2 is None, "Should not receive second fragment without confirming first"

        await master_ch.close()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
