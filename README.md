# dnp3py

[![CI](https://github.com/craigpnnl/dnp3py/actions/workflows/ci.yml/badge.svg)](https://github.com/craigpnnl/dnp3py/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/craigpnnl/dnp3py/graph/badge.svg)](https://codecov.io/gh/craigpnnl/dnp3py)
[![PyPI version](https://img.shields.io/pypi/v/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![Python versions](https://img.shields.io/pypi/pyversions/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

A pure Python implementation of the DNP3 (IEEE 1815-2012) protocol, including a
MESA IEEE 1815.2 DER outstation simulator introduced in v0.2.0.

## Features

- **Pure Python** - No C/C++ dependencies, works anywhere Python runs
- **Level 2 object model** - targets the IEEE 1815-2012 clause 14.4 (Table 14-3)
  subset for RTU-class SCADA use; see [Protocol Conformance](#protocol-conformance)
  for the one known gap
- **Async I/O** - Built on asyncio for efficient network communication
- **Type Safe** - Full type annotations with strict mypy compliance
- **Well Tested** - see the CI and codecov badges above for current numbers
- **MESA IEEE 1815.2 Outstation** - Profile-driven DER outstation simulator for
  meters, DERs, inverters, and batteries

## Installation

```bash
pip install dnp3py
```

Or with [pixi](https://pixi.sh):

```bash
pixi add dnp3py
```

## Quick Start

Run the outstation script in one terminal, then the master script in a
second; both use `127.0.0.1:20000`, so the master's integrity poll returns
the two points the outstation set.

### Outstation (Server)

```python
import asyncio
from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner

async def main():
    # Create database with points
    database = Database()
    database.add_binary_input(0, BinaryInputConfig())
    database.add_analog_input(0, AnalogInputConfig())

    # Update values
    database.update_binary_input(0, value=True)
    # Static Analog Input transmits as a 32-bit integer by default (g30v1);
    # a fractional value here is silently truncated on the wire.
    database.update_analog_input(0, value=42)

    # Create outstation and run it over TCP
    outstation = Outstation(database=database, config=OutstationConfig(address=1))
    runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=20000)
    await runner.run()  # serves connections until runner.stop() is called

asyncio.run(main())
```

### Master (Client)

```python
import asyncio
from dnp3.master import DefaultSOEHandler, Master, MasterConfig, MasterTcpRunner

async def main():
    # Create master with event handler
    handler = DefaultSOEHandler()
    master = Master(handler=handler, config=MasterConfig(address=2, outstation_address=1))

    # Connect and perform an integrity poll
    async with MasterTcpRunner(master=master, host="127.0.0.1", port=20000) as runner:
        await runner.integrity_poll()

    print(handler.binary_inputs[0].value)   # True
    print(handler.analog_inputs[0].value)   # 42.0

asyncio.run(main())
```

## MESA IEEE 1815.2 Outstation

The `dnp3.mesa` module is a DER-oriented outstation built on mesa-tool's
PicsProfile format (the companion Rust conformance control station); see
[docs/mesa-outstation.md](docs/mesa-outstation.md) for the format and the
adoption rationale. It supports meters, DERs (distributed energy resources),
inverters, and batteries, plus counters, curves, and schedules. You describe
the device by loading a PicsProfile JSON file; the module builds the DNP3
database and command handler automatically, scaling analog values from
engineering units to DNP3 transmission integers on load.

Four bundled profiles ship inside the package
(`full`, `mandatory_1815`, `mandatory_1547`, `minimal_1547`); `full` is the
default. Profiles are authored as JSON; there is no spreadsheet ingestion
path.

### Quick start (CLI)

```bash
# Run against the bundled full profile (the default)
python -m dnp3.mesa

# Run against a conformance subset
python -m dnp3.mesa --profile-name minimal_1547

# Run a custom profile, limited to the first meter and no DERs/inverters/batteries
python -m dnp3.mesa --profile my_device_profile.json --meters 1 --ders 0 --inverters 0 --batteries 0
```

For the full flag reference and defaults, see
[docs/mesa-outstation.md](docs/mesa-outstation.md).

### Programmatic API

```python
import asyncio
from pathlib import Path
from dnp3.mesa.outstation import create_mesa_outstation

async def main():
    outstation = create_mesa_outstation(
        profile_path=Path("my_device_profile.json"),
        host="0.0.0.0",
        port=20000,
        address=1,
        master_address=0,
        entity_overrides={"meters": 1, "ders": 0},  # optional
    )
    await outstation.run()

asyncio.run(main())
```

`create_mesa_outstation` returns a `MesaOutstation` dataclass. Call
`await outstation.run()` to start the TCP server; call `await outstation.stop()`
to shut it down cleanly.

For a full description of the PicsProfile format, the bundled profiles, the
engineering-to-transmission scaling contract, and CTR/curve/schedule
handling, see [docs/mesa-outstation.md](docs/mesa-outstation.md).

## Protocol Conformance

### Function Codes

`CONFIRM`, `READ`, `WRITE`, `SELECT`, `OPERATE`, `DIRECT_OPERATE`,
`DIRECT_OPERATE_NO_ACK`, `COLD_RESTART`, `WARM_RESTART`, `DELAY_MEASURE`,
`ENABLE_UNSOLICITED`, `DISABLE_UNSOLICITED`, `IMMEDIATE_FREEZE`,
`IMMEDIATE_FREEZE_NO_ACK`, `FREEZE_CLEAR`, `FREEZE_CLEAR_NO_ACK` (IEEE
1815-2012 Clause 4). Control commands are covered in detail, with wire-level
request/response encoding, in
[docs/control-commands.md](docs/control-commands.md).

### Object Groups (outstation)

| Group | Description |
|-------|-------------|
| 1, 2 | Binary Input (static, event) |
| 10 | Binary Output (static) |
| 12 | Control Relay Output Block (select, operate, direct operate) |
| 20, 21, 22 | Counter (static, frozen, event) |
| 30, 32 | Analog Input (static, event) |
| 40, 41 | Analog Output (status, command: select, operate, direct operate) |
| 52 | Time Delay (response to DELAY_MEASURE) |
| 60 | Class data |
| 80 | Internal Indications (WRITE to clear DEVICE_RESTART) |

Wire layout follows IEEE 1815-2012 Annex A. The master additionally decodes
and delivers Double-Bit Binary Input (groups 3, 4) from a peer that sends it,
on its own handler callback (`DoubleBitInputHandler`); a few other groups the
wire layout recognizes (command events, frozen analog input, deadband, time)
are framed but not delivered to any handler.

### Level 2 (clause 14.4, Table 14-3)

The outstation implements every Table 14-3 row except one: it silently
ignores WRITE requests for Group 50 (time synchronization) rather than
parsing them, and never issues Group 51 (Time and Date CTO) responses. A
master relying on DNP3 clock sync against this outstation will not get one.

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/craigpnnl/dnp3py.git
cd dnp3py

# Install with pixi
pixi install
pixi run dev-install

# Set up pre-commit hooks (enforces quality checks before commits)
pixi run pre-commit-install

# Run tests
pixi run test

# Run with coverage
pixi run test-cov

# Lint and type check
pixi run check

# Test with a specific Python version (default, py311, py312, py313, py314)
pixi run -e py311 test
pixi run -e py312 test

# Test all Python versions (via nox)
pixi run nox
```

See [CHANGELOG.md](CHANGELOG.md) for release notes and upgrade notes between
versions.

### Project Structure

```
dnp3py/
+-- src/dnp3/
|   +-- core/           # CRC, types, enums, flags
|   +-- datalink/       # Data link layer (frames, parsing)
|   +-- transport/      # Transport layer (segmentation)
|   +-- application/    # Application layer (messages)
|   +-- objects/        # DNP3 object definitions
|   +-- database/       # Point database and events
|   +-- outstation/     # Outstation implementation
|   +-- master/         # Master implementation
|   +-- mesa/           # MESA IEEE 1815.2 DER outstation
|   |   +-- data/profiles/  # Bundled PicsProfile JSON files (full.json default)
|   +-- transport_io/   # TCP/simulator channels
+-- tests/
    +-- unit/           # Unit tests
    +-- integration/    # Integration tests
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

This implementation follows the IEEE 1815-2012 standard for DNP3.
