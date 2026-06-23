"""CLI entry point: python -m dnp3.mesa"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dnp3.mesa.outstation import create_mesa_outstation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MESA IEEE 1815.2 Outstation Simulator",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        required=True,
        help="Path to profile.json",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Listen address")
    parser.add_argument("--port", type=int, default=20000, help="Listen port")
    parser.add_argument(
        "--address",
        type=int,
        default=1,
        help="DNP3 outstation address",
    )
    parser.add_argument(
        "--master-address",
        type=int,
        default=0,
        help="Expected master address",
    )
    parser.add_argument("--meters", type=int, default=None, help="Number of meters")
    parser.add_argument("--ders", type=int, default=None, help="Number of DERs")
    parser.add_argument(
        "--inverters",
        type=int,
        default=None,
        help="Number of inverters",
    )
    parser.add_argument(
        "--batteries",
        type=int,
        default=None,
        help="Number of batteries",
    )

    args = parser.parse_args()

    entity_overrides: dict[str, int] = {}
    if args.meters is not None:
        entity_overrides["meters"] = args.meters
    if args.ders is not None:
        entity_overrides["ders"] = args.ders
    if args.inverters is not None:
        entity_overrides["inverters"] = args.inverters
    if args.batteries is not None:
        entity_overrides["batteries"] = args.batteries

    outstation = create_mesa_outstation(
        profile_path=args.profile,
        host=args.host,
        port=args.port,
        address=args.address,
        master_address=args.master_address,
        entity_overrides=entity_overrides or None,
    )

    print(f"MESA Outstation starting on {args.host}:{args.port}")
    print(f"  DNP3 address: {args.address}")
    print(
        f"  Points: {outstation.database.binary_input_count} BI, "
        f"{outstation.database.binary_output_count} BO, "
        f"{outstation.database.analog_input_count} AI, "
        f"{len(outstation.ao_store)} AO",
    )
    print(f"  Entities: {len(outstation.entities)}")

    asyncio.run(outstation.run())


if __name__ == "__main__":
    main()
