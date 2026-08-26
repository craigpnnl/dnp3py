"""End-to-end tests: `MasterTcpRunner` against a live `Outstation` over TCP.

`test_tcp_master_values_e2e.py` proves a `Master` can decode what an
`Outstation` sends, but hand-rolls the link and transport layers in the test
itself -- which is the duplication `MasterTcpRunner` exists to remove. These
tests drive the runner instead, so the stack under test is the shipped one.

Sockets bind to `127.0.0.1` on port 0 and the runner is told the port the OS
chose, so nothing here depends on a fixed port, a hostname, or a filesystem
path.

Both event-class settings are covered because they produce different response
shapes: `EventClass.CLASS_1` makes an integrity poll return event groups (2/32)
with count qualifiers, `EventClass.NONE` returns static groups (1/30) with range
qualifiers.
"""

from __future__ import annotations

import asyncio

import pytest

from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database, EventClass
from dnp3.master import Master, MasterConfig, MasterTcpRunner
from dnp3.master.handler import ResponseInfo
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner

MASTER_ADDR = 3
OUTSTATION_ADDR = 1
BIND_TIMEOUT = 5.0
POLL_TIMEOUT = 5.0

# The smallest fragment the outstation allows, so a modest point count still
# spans several fragments and exercises the CONFIRM handshake.
MIN_FRAGMENT_SIZE = 249
ANALOG_COUNT = 100  # the database's default cap


class RecordingHandler:
    """Records every value the master delivers, keyed by index."""

    def __init__(self) -> None:
        self.binary_inputs: dict[int, bool] = {}
        self.analog_inputs: dict[int, float] = {}
        self.responses: list[ResponseInfo] = []

    def on_binary_input(self, values: list, info: ResponseInfo) -> None:
        self.binary_inputs.update({v.index: v.value for v in values})

    def on_binary_output(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_analog_input(self, values: list, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})

    def on_analog_output(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_counter(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_frozen_counter(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_response(self, info: ResponseInfo) -> None:
        self.responses.append(info)


async def _await_bind(runner: OutstationTcpRunner) -> tuple[str, int]:
    """Wait for the outstation runner to bind, returning its address."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BIND_TIMEOUT
    while loop.time() < deadline:
        if runner.is_running and runner.local_address is not None:
            return runner.local_address
        await asyncio.sleep(0.02)
    pytest.fail("outstation runner did not bind in time")


async def _poll_over_tcp(
    database: Database,
    *,
    max_fragment_size: int | None = None,
) -> tuple[RecordingHandler, list[ResponseInfo]]:
    """Run one integrity poll through `MasterTcpRunner` over a real socket.

    Args:
        database: Outstation database to serve.
        max_fragment_size: Outstation fragment cap, to force a multi-fragment
            response when small.

    Returns:
        The recording handler and the burst's per-fragment info.
    """
    extra = {} if max_fragment_size is None else {"max_fragment_size": max_fragment_size}
    outstation_config = OutstationConfig(
        address=OUTSTATION_ADDR,
        master_address=MASTER_ADDR,
        **extra,
    )
    outstation = Outstation(config=outstation_config, database=database)
    os_runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
    serve_task = asyncio.create_task(os_runner.run())

    handler = RecordingHandler()
    master = Master(
        config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
        handler=handler,
    )

    try:
        host, port = await _await_bind(os_runner)
        runner = MasterTcpRunner(master=master, host=host, port=port, response_timeout=POLL_TIMEOUT)
        async with runner:
            infos = await asyncio.wait_for(runner.integrity_poll(), timeout=POLL_TIMEOUT)
    finally:
        await os_runner.stop()
        # Cancel before awaiting: the accept loop parks in `accept()` and would
        # otherwise burn the full timeout before finishing.
        serve_task.cancel()
        with pytest.raises((asyncio.CancelledError, TimeoutError)):
            await asyncio.wait_for(serve_task, timeout=POLL_TIMEOUT)

    return handler, infos


class TestIntegrityPollOverTcp:
    """One integrity poll, both event-class configurations."""

    async def test_event_class_values_decode(self) -> None:
        """Event-group responses (2/32) decode to the stored values."""
        database = Database()
        for index in (0, 1, 2):
            database.add_binary_input(index, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_binary_input(2, value=True, quality=BinaryQuality.ONLINE)
        database.update_analog_input(0, value=-1500, quality=AnalogQuality.ONLINE)

        handler, infos = await _poll_over_tcp(database)

        assert handler.binary_inputs == {0: True, 1: False, 2: True}
        assert handler.analog_inputs == {0: -1500.0}
        assert infos[-1].fin is True

    async def test_static_group_values_decode(self) -> None:
        """Static-group responses (1/30) decode to the stored values."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.NONE))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.NONE))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.update_analog_input(0, value=2401, quality=AnalogQuality.ONLINE)

        handler, infos = await _poll_over_tcp(database)

        assert handler.binary_inputs == {0: True, 1: False}
        assert handler.analog_inputs == {0: 2401.0}
        assert infos[-1].fin is True


class TestMultiFragmentOverTcp:
    """A burst that spans fragments, exercising the CONFIRM handshake live.

    This is the case that stalls without a runner: the outstation sets CON on
    every non-final fragment and blocks in `_wait_for_confirm` until its confirm
    timer expires, so a master that does not answer sees only fragment one.

    It is also the cross-check on #61: the outstation now increments the
    application sequence per fragment, and the runner's walk requires that. If
    either side regressed, this deadlocks instead of passing.
    """

    async def test_all_fragments_arrive_and_confirm(self) -> None:
        """Every value survives a multi-fragment burst over a real socket."""
        database = Database()
        expected = {}
        for index in range(ANALOG_COUNT):
            database.add_analog_input(index, AnalogInputConfig(event_class=EventClass.NONE))
            database.update_analog_input(index, value=index * 10, quality=AnalogQuality.ONLINE)
            expected[index] = float(index * 10)

        handler, infos = await _poll_over_tcp(database, max_fragment_size=MIN_FRAGMENT_SIZE)

        assert len(infos) > 1, "expected a multi-fragment burst"
        assert [i.fin for i in infos[:-1]] == [False] * (len(infos) - 1)
        assert infos[-1].fin is True
        assert handler.analog_inputs == expected

    async def test_fragment_sequences_increment(self) -> None:
        """Fragment sequences advance by one, modulo 16, across the burst."""
        database = Database()
        for index in range(ANALOG_COUNT):
            database.add_analog_input(index, AnalogInputConfig(event_class=EventClass.NONE))
            database.update_analog_input(index, value=float(index), quality=AnalogQuality.ONLINE)

        _, infos = await _poll_over_tcp(database, max_fragment_size=MIN_FRAGMENT_SIZE)

        sequences = [i.sequence for i in infos]
        expected = [(sequences[0] + offset) % 16 for offset in range(len(sequences))]
        assert sequences == expected
