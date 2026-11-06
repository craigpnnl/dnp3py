"""End-to-end: analog output variations from `MasterTcpRunner` to a live `Outstation` over TCP.

`test_commands.py` pins the g41 record layouts in memory; these tests send a
setpoint in each non-default variation through the shipped stack over a real
socket and check that the value the outstation's handler receives is the one
the master meant. Variation 1 would truncate 2.5 to 2 and could not carry a
double's precision, so the values below only survive in the variation chosen.
"""

from __future__ import annotations

import asyncio

import pytest

from dnp3.database import AnalogOutputConfig, Database
from dnp3.master import DefaultSOEHandler, Master, MasterConfig, MasterTcpRunner
from dnp3.master.commands import (
    ANALOG_OUTPUT_16_VARIATION,
    ANALOG_OUTPUT_DOUBLE_VARIATION,
    ANALOG_OUTPUT_FLOAT_VARIATION,
)
from dnp3.outstation import CommandResult, DefaultCommandHandler, Outstation, OutstationConfig, OutstationTcpRunner

MASTER_ADDR = 3
OUTSTATION_ADDR = 1
BIND_TIMEOUT = 5.0
EXCHANGE_TIMEOUT = 5.0


class RecordingHandler(DefaultCommandHandler):
    """Accepts every analog setpoint and records what arrived."""

    def __init__(self) -> None:
        self.received: list[tuple[int, float]] = []

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        self.received.append((index, value))
        return CommandResult.success()


async def _await_bind(runner: OutstationTcpRunner) -> tuple[str, int]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BIND_TIMEOUT
    while loop.time() < deadline:
        if runner.is_running and runner.local_address is not None:
            return runner.local_address
        await asyncio.sleep(0.02)
    pytest.fail("outstation runner did not bind in time")


@pytest.mark.parametrize(
    ("variation", "value"),
    [
        (ANALOG_OUTPUT_FLOAT_VARIATION, 2.5),
        (ANALOG_OUTPUT_DOUBLE_VARIATION, 1.0000000000000002),
        (ANALOG_OUTPUT_16_VARIATION, -7),
    ],
    ids=["flt32", "flt64", "int16"],
)
async def test_setpoint_arrives_in_the_variation_sent(variation: int, value: float) -> None:
    database = Database()
    database.add_analog_output(0, AnalogOutputConfig())
    handler = RecordingHandler()
    outstation = Outstation(
        config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR),
        database=database,
        handler=handler,
    )
    os_runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
    serve_task = asyncio.create_task(os_runner.run())
    master = Master(
        config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR), handler=DefaultSOEHandler()
    )
    try:
        host, port = await _await_bind(os_runner)
        runner = MasterTcpRunner(master=master, host=host, port=port, response_timeout=EXCHANGE_TIMEOUT)
        async with runner:
            task = master.command_builder().add_analog(0, value, variation=variation).build_direct_operate()
            infos = await asyncio.wait_for(runner.request(master.build_direct_operate(task)), timeout=EXCHANGE_TIMEOUT)
    finally:
        await os_runner.stop()
        serve_task.cancel()
        with pytest.raises((asyncio.CancelledError, TimeoutError)):
            await asyncio.wait_for(serve_task, timeout=EXCHANGE_TIMEOUT)

    assert len(infos) == 1
    assert handler.received == [(0, value)]
