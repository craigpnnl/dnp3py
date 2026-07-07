# dnp3py

[![CI](https://github.com/craig8/dnp3py/actions/workflows/ci.yml/badge.svg)](https://github.com/craig8/dnp3py/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/craig8/dnp3py/graph/badge.svg)](https://codecov.io/gh/craig8/dnp3py)
[![PyPI version](https://img.shields.io/pypi/v/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![Python versions](https://img.shields.io/pypi/pyversions/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

A pure Python implementation of the DNP3 (IEEE 1815-2012) protocol, including a
MESA IEEE 1815.2 DER outstation simulator introduced in v0.2.0.

## Features

- **Pure Python** - No C/C++ dependencies, works anywhere Python runs
- **Level 2 Subset** - RTU-class functionality for SCADA applications
- **Async I/O** - Built on asyncio for efficient network communication
- **Type Safe** - Full type annotations with strict mypy compliance
- **Well Tested** - Comprehensive test suite with 98%+ code coverage
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

### Outstation (Server)

```python
import asyncio
from dnp3.database import Database, BinaryInputConfig, AnalogInputConfig
from dnp3.outstation import Outstation
from dnp3.transport_io import TcpServer

async def main():
    # Create database with points
    database = Database()
    database.add_binary_input(0, BinaryInputConfig())
    database.add_analog_input(0, AnalogInputConfig())

    # Update values
    database.update_binary_input(0, value=True)
    database.update_analog_input(0, value=25.5)

    # Create outstation
    outstation = Outstation(database=database)

    # Start TCP server
    server = TcpServer(host="0.0.0.0", port=20000)
    await server.start()

    # Handle connections...

asyncio.run(main())
```

### Master (Client)

```python
import asyncio
from dnp3.master import Master, DefaultSOEHandler
from dnp3.transport_io import TcpClientChannel

async def main():
    # Create master with event handler
    handler = DefaultSOEHandler()
    master = Master(handler=handler)

    # Connect to outstation
    channel = TcpClientChannel(host="localhost", port=20000)
    await channel.open()

    # Perform integrity poll
    request = master.build_integrity_poll()
    # Send request, receive response...

asyncio.run(main())
```

## MESA IEEE 1815.2 Outstation

The `dnp3.mesa` module is a DER-oriented outstation built on mesa-tool's
PicsProfile format, the same profile shape mesa-tool's Rust conformance
control station uses. It supports meters, DERs (distributed energy
resources), inverters, and batteries, plus counters, curves, and schedules.
You describe the device by loading a PicsProfile JSON file; the module builds
the DNP3 database and command handler automatically, scaling analog values
from engineering units to DNP3 transmission integers on load.

Four bundled profiles ship inside the package
(`full`, `mandatory_1815`, `mandatory_1547`, `minimal_1547`); `full` is the
default. Profiles are authored as JSON; there is no spreadsheet ingestion
path.

### Quick start (CLI)

```
usage: python -m dnp3.mesa [-h] [--profile PROFILE]
                           [--profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}]
                           [--host HOST] [--port PORT] [--address ADDRESS]
                           [--master-address MASTER_ADDRESS] [--meters METERS]
                           [--ders DERS] [--inverters INVERTERS]
                           [--batteries BATTERIES]

options:
  --profile PROFILE           Path to a PicsProfile JSON file (default: bundled full.json)
  --profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}
                              Select a bundled profile by name instead of --profile
                              (mutually exclusive with --profile)
  --host HOST                 Listen address (default: 0.0.0.0)
  --port PORT                 Listen port (default: 20000)
  --address ADDRESS           DNP3 outstation address (default: 1)
  --master-address MASTER_ADDRESS
                              Expected master address (default: 0)
  --meters METERS             Number of meter instances to include
  --ders DERS                 Number of DER instances to include
  --inverters INVERTERS       Number of inverter instances to include
  --batteries BATTERIES       Number of battery instances to include
```

Run the simulator against the bundled full profile (the default, so
`--profile`/`--profile-name` can be omitted):

```bash
python -m dnp3.mesa
```

Run against a conformance subset, or a custom profile:

```bash
python -m dnp3.mesa --profile-name minimal_1547
python -m dnp3.mesa --profile my_device_profile.json
```

The `--meters`, `--ders`, `--inverters`, and `--batteries` flags include only
the first N instances of that equipment type, letting a single shared
profile serve devices with different hardware configurations without editing
the file:

```bash
# Include only the first meter; exclude DERs, inverters, and batteries.
python -m dnp3.mesa --profile-name full --meters 1 --ders 0 --inverters 0 --batteries 0
```

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

## Supported Features

### Function Codes
- READ, WRITE
- SELECT, OPERATE, DIRECT_OPERATE
- COLD_RESTART, WARM_RESTART
- ENABLE_UNSOLICITED, DISABLE_UNSOLICITED
- DELAY_MEASURE

### Object Groups
| Group | Description |
|-------|-------------|
| 1, 2 | Binary Input (static, event) |
| 10, 11, 12 | Binary Output (static, event, CROB) |
| 20, 21, 22 | Counter (static, frozen, event) |
| 30, 32 | Analog Input (static, event) |
| 40, 41, 42 | Analog Output (static, command, event) |
| 50, 51, 52 | Time objects |
| 60 | Class data |

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/craig8/dnp3py.git
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

# Test with specific Python version
pixi run -e py310 test
pixi run -e py312 test

# Test all Python versions (via nox)
pixi run nox
```

### Project Structure

```
dnp3py/
├── src/dnp3/
│   ├── core/           # CRC, types, enums, flags
│   ├── datalink/       # Data link layer (frames, parsing)
│   ├── transport/      # Transport layer (segmentation)
│   ├── application/    # Application layer (messages)
│   ├── objects/        # DNP3 object definitions
│   ├── database/       # Point database and events
│   ├── outstation/     # Outstation implementation
│   ├── master/         # Master implementation
│   ├── mesa/           # MESA IEEE 1815.2 DER outstation
│   │   └── data/profiles/  # Bundled PicsProfile JSON files (full.json default)
│   └── transport_io/   # TCP/simulator channels
└── tests/
    ├── unit/           # Unit tests
    └── integration/    # Integration tests
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

This implementation follows the IEEE 1815-2012 standard for DNP3.
