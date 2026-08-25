"""End-to-end TCP polls that assert the values a master recovers.

`test_tcp_outstation_e2e.py` proves the transport stack carries a response
(`function == RESPONSE`); it does not check what the response decodes to. These
tests close that loop: a real `Master` parses the bytes a real `Outstation`
sent over a real socket, and the assertions are on the point values.

The configuration under test is `EventClass.CLASS_1`, the ordinary SCADA
setting, which makes an integrity poll return event groups (2 / 32) with count
qualifiers rather than static groups (1 / 30).

Regression cover for the response-parsing bugs reported in issue #30.
"""

import asyncio

import pytest

from dnp3.core.enums import LinkFunctionCode
from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database, EventClass
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.parser import FrameParser
from dnp3.master import Master
from dnp3.master.handler import ResponseInfo, SOEHandler
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner
from dnp3.transport.segment import TransportSegment

MASTER_ADDR = 3
OUTSTATION_ADDR = 1
READ_TIMEOUT = 2.0
BIND_TIMEOUT = 5.0


class RecordingHandler(SOEHandler):
    """Records every value the master delivers, keyed by index."""

    def __init__(self) -> None:
        self.binary_inputs: dict[int, bool] = {}
        self.analog_inputs: dict[int, float] = {}

    def on_binary_input(self, values, info: ResponseInfo) -> None:
        self.binary_inputs.update({v.index: v.value for v in values})

    def on_analog_input(self, values, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})


def _frame_request(request_bytes: bytes) -> bytes:
    """Wrap an application request in a transport segment and link frame."""
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request_bytes)
    frame = build_unconfirmed_user_data(
        destination=OUTSTATION_ADDR,
        source=MASTER_ADDR,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


async def _await_bind(runner: OutstationTcpRunner) -> tuple[str, int]:
    """Wait for the runner to bind, returning its address."""
    deadline = asyncio.get_running_loop().time() + BIND_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        if runner.is_running and runner.local_address is not None:
            return runner.local_address
        await asyncio.sleep(0.02)
    pytest.fail("outstation runner did not bind in time")


async def _poll_values(database: Database) -> RecordingHandler:
    """Run one integrity poll over TCP and return what the master decoded."""
    outstation = Outstation(
        config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR),
        database=database,
    )
    runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
    run_task = asyncio.create_task(runner.run())

    handler = RecordingHandler()
    master = Master(handler=handler)

    try:
        host, port = await _await_bind(runner)
        reader, writer = await asyncio.open_connection(host, port)
        parser = FrameParser()
        try:
            # Reset the link, then confirm the outstation ACKs before polling.
            writer.write(
                build_reset_link_state(
                    destination=OUTSTATION_ADDR,
                    source=MASTER_ADDR,
                    dir_from_master=True,
                ).to_bytes()
            )
            await writer.drain()
            ack_data = await asyncio.wait_for(reader.read(4096), timeout=READ_TIMEOUT)
            ack_frames = list(parser.feed(ack_data))
            assert ack_frames, "outstation sent no link ACK"
            assert ack_frames[0].header.control.function_code == LinkFunctionCode.SEC_ACK

            writer.write(_frame_request(master.build_integrity_poll().to_bytes()))
            await writer.drain()

            response_data = await asyncio.wait_for(reader.read(4096), timeout=READ_TIMEOUT)
            for frame in parser.feed(response_data):
                if not frame.user_data:
                    continue
                segment = TransportSegment.from_bytes(frame.user_data)
                assert master.process_response(segment.payload) is not None
        finally:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=READ_TIMEOUT)
    finally:
        await runner.stop()
        try:
            await asyncio.wait_for(run_task, timeout=READ_TIMEOUT)
        except (TimeoutError, asyncio.CancelledError):
            run_task.cancel()

    return handler


class TestTcpMasterValuesE2E:
    """Values decoded by a master from a live outstation over TCP."""

    @pytest.mark.asyncio
    async def test_event_class_binaries_decode_correctly(self) -> None:
        """Three event-class binaries arrive with their stored states."""
        database = Database()
        for index in (0, 1, 2):
            database.add_binary_input(index, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_binary_input(2, value=True, quality=BinaryQuality.ONLINE)

        handler = await _poll_values(database)

        assert handler.binary_inputs == {0: True, 1: False, 2: True}

    @pytest.mark.asyncio
    async def test_mixed_types_all_arrive_over_tcp(self) -> None:
        """A multi-block response delivers both binary and analog values."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.NONE))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_analog_input(0, value=2401, quality=AnalogQuality.ONLINE)

        handler = await _poll_values(database)

        assert handler.binary_inputs == {0: True, 1: False}
        assert handler.analog_inputs == {0: 2401.0}

    @pytest.mark.asyncio
    async def test_event_class_analog_is_not_fabricated(self) -> None:
        """One event-class analog stays one point with its stored value."""
        database = Database()
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1))
        database.update_analog_input(0, value=-1500, quality=AnalogQuality.ONLINE)

        handler = await _poll_values(database)

        assert handler.analog_inputs == {0: -1500.0}
