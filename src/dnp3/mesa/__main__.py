"""CLI entry point: python -m dnp3.mesa"""

from __future__ import annotations

import argparse
import asyncio
from importlib.resources import files
from pathlib import Path

from dnp3.mesa.outstation import create_mesa_outstation

#: Selector name -> packaged profile filename, for --profile-name.
_PROFILE_NAMES = {
    "full": "full.json",
    "mandatory_1815": "mandatory_1815.json",
    "mandatory_1547": "mandatory_1547.json",
    "minimal_1547": "minimal_1547.json",
}


def _packaged_profile_path(filename: str) -> Path:
    """Resolve a bundled profile file via importlib.resources.

    Uses importlib.resources (not a __file__-relative path) so the lookup
    works whether dnp3py is running from a source checkout or installed
    from a wheel; the data lives at src/dnp3/mesa/data/profiles/, inside
    the package, so hatchling's default wheel packaging ships it and an
    editable install sees it too.
    """
    resource = files("dnp3.mesa") / "data" / "profiles" / filename
    return Path(str(resource))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MESA IEEE 1815.2 Outstation Simulator",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to a PicsProfile JSON file (default: bundled full.json)",
    )
    parser.add_argument(
        "--profile-name",
        choices=sorted(_PROFILE_NAMES),
        default=None,
        help="Select a bundled profile by name instead of --profile (mutually exclusive)",
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

    if args.profile is not None and args.profile_name is not None:
        parser.error("--profile and --profile-name are mutually exclusive")

    if args.profile is not None:
        profile_path = args.profile
    elif args.profile_name is not None:
        profile_path = _packaged_profile_path(_PROFILE_NAMES[args.profile_name])
    else:
        profile_path = _packaged_profile_path(_PROFILE_NAMES["full"])

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
        profile_path=profile_path,
        host=args.host,
        port=args.port,
        address=args.address,
        master_address=args.master_address,
        entity_overrides=entity_overrides or None,
    )

    print(f"MESA Outstation starting on {args.host}:{args.port}")
    print(f"  Profile: {profile_path}")
    print(f"  DNP3 address: {args.address}")
    print(
        f"  Points: {outstation.database.binary_input_count} BI, "
        f"{outstation.database.binary_output_count} BO, "
        f"{outstation.database.analog_input_count} AI, "
        f"{len(outstation.ao_store)} AO, "
        f"{outstation.database.counter_count} CTR",
    )
    print(f"  Curves: {len(outstation.profile.ai.curves)}")
    print(f"  Entities: {len(outstation.entities)}")

    asyncio.run(outstation.run())


if __name__ == "__main__":
    main()
