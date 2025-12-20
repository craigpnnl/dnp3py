# dnp3py

[![CI](https://github.com/craig8/dnp3py/actions/workflows/ci.yml/badge.svg)](https://github.com/craig8/dnp3py/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/craig8/dnp3py/graph/badge.svg)](https://codecov.io/gh/craig8/dnp3py)
[![PyPI version](https://img.shields.io/pypi/v/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![Python versions](https://img.shields.io/pypi/pyversions/dnp3py.svg)](https://pypi.org/project/dnp3py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

A pure Python implementation of the DNP3 (IEEE 1815-2012) protocol.

## Features

- **Pure Python** - No C/C++ dependencies, works anywhere Python runs
- **Level 2 Subset** - RTU-class functionality for SCADA applications
- **Async I/O** - Built on asyncio for efficient network communication
- **Type Safe** - Full type annotations with strict mypy compliance
- **Well Tested** - Comprehensive test suite with 98%+ code coverage

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
│   └── transport_io/   # TCP/simulator channels
└── tests/
    ├── unit/           # Unit tests
    └── integration/    # Integration tests
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

This implementation follows the IEEE 1815-2012 standard for DNP3.
