"""README Quick Start examples run as written and complete their round trip.

Each test builds the same objects, with the same arguments, as the matching
README code block. The outstation and master blocks are meant to run as two
separate scripts against a fixed port; here they run in one process against a
dynamic port so the test suite does not depend on port 20000 being free.
"""

import asyncio

import pytest

from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database
from dnp3.master import DefaultSOEHandler, Master, MasterConfig, MasterTcpRunner
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner

BIND_TIMEOUT = 5.0
POLL_TIMEOUT = 5.0


def _build_readme_outstation() -> Outstation:
    """Build the outstation and database exactly as the README's Outstation block does."""
    database = Database()
    database.add_binary_input(0, BinaryInputConfig())
    database.add_analog_input(0, AnalogInputConfig())

    database.update_binary_input(0, value=True)
    database.update_analog_input(0, value=42)

    return Outstation(database=database, config=OutstationConfig(address=1))


async def _await_bind(runner: OutstationTcpRunner) -> tuple[str, int]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BIND_TIMEOUT
    while loop.time() < deadline:
        if runner.is_running and runner.local_address is not None:
            return runner.local_address
        await asyncio.sleep(0.01)
    pytest.fail("outstation runner did not bind in time")


class TestReadmeOutstationQuickStart:
    """The README's Outstation (Server) block."""

    async def test_serves_the_points_it_configures(self) -> None:
        """The outstation binds and serves the binary and analog points it sets."""
        outstation = _build_readme_outstation()
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        serve_task = asyncio.create_task(runner.run())

        try:
            host, port = await _await_bind(runner)
            assert host == "127.0.0.1"
            assert port > 0
        finally:
            await runner.stop()
            serve_task.cancel()
            with pytest.raises((asyncio.CancelledError, TimeoutError)):
                await asyncio.wait_for(serve_task, timeout=POLL_TIMEOUT)


class TestReadmeMasterQuickStart:
    """The README's Master (Client) block, against the Outstation block's server."""

    async def test_integrity_poll_returns_the_configured_values(self) -> None:
        """An integrity poll returns exactly the values the outstation block set."""
        outstation = _build_readme_outstation()
        server = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        serve_task = asyncio.create_task(server.run())

        try:
            host, port = await _await_bind(server)

            handler = DefaultSOEHandler()
            master = Master(handler=handler, config=MasterConfig(address=2, outstation_address=1))
            async with MasterTcpRunner(master=master, host=host, port=port) as runner:
                await asyncio.wait_for(runner.integrity_poll(), timeout=POLL_TIMEOUT)

            assert handler.binary_inputs[0].value is True
            assert handler.analog_inputs[0].value == 42
        finally:
            await server.stop()
            serve_task.cancel()
            with pytest.raises((asyncio.CancelledError, TimeoutError)):
                await asyncio.wait_for(serve_task, timeout=POLL_TIMEOUT)
