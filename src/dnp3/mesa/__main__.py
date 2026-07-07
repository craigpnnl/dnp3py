"""CLI entry point: python -m dnp3.mesa"""

from __future__ import annotations

import argparse
import asyncio
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path

from dnp3.mesa.outstation import MesaOutstation, create_mesa_outstation

#: The package the bundled profile data lives under (src/dnp3/mesa/data/).
_PACKAGE = "dnp3.mesa"

#: Selector name -> packaged profile filename, for --profile-name.
_PROFILE_NAMES = {
    "full": "full.json",
    "mandatory_1815": "mandatory_1815.json",
    "mandatory_1547": "mandatory_1547.json",
    "minimal_1547": "minimal_1547.json",
}


def _packaged_profile_resource(filename: str) -> Traversable:
    """Locate a bundled profile file via importlib.resources.

    Returns a Traversable (not a Path): the profile data lives at
    src/dnp3/mesa/data/profiles/, inside the package, so a regular wheel
    or editable install exposes it as a real file, but importlib.resources
    does not guarantee that in general (a zipapp or a zip-imported package
    has no real filesystem path for it). Callers open it via
    importlib.resources.as_file, never by stringifying this value into a
    Path directly.
    """
    return files(_PACKAGE) / "data" / "profiles" / filename


def _packaged_profile_display(filename: str) -> str:
    """A stable display identity for a bundled profile.

    Used in the startup summary instead of the real filesystem path
    as_file may materialize: that path can be a temporary extraction (under
    zipimport) that no longer exists once the as_file context exits, so it
    is not a meaningful thing to show the operator.
    """
    return f"{_PACKAGE}:data/profiles/{filename} (packaged)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MESA IEEE 1815.2 Outstation Simulator",
    )
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Path to a PicsProfile JSON file (default: bundled full.json)",
    )
    profile_group.add_argument(
        "--profile-name",
        choices=sorted(_PROFILE_NAMES),
        default=None,
        help="Select a bundled profile by name instead of --profile",
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

    outstation_kwargs = {
        "host": args.host,
        "port": args.port,
        "address": args.address,
        "master_address": args.master_address,
        "entity_overrides": entity_overrides or None,
    }

    if args.profile is not None:
        # A user-supplied path: load it directly, no resource extraction.
        profile_display = str(args.profile)
        outstation: MesaOutstation = create_mesa_outstation(profile_path=args.profile, **outstation_kwargs)
    else:
        # A bundled profile: importlib.resources may need to materialize it
        # to a real filesystem path (zipimport, zipapp). load_profile MUST
        # run inside the as_file context; the extracted path is only valid
        # for the lifetime of the `with` block, so create_mesa_outstation
        # (which calls load_profile internally) is called from inside it.
        filename = _PROFILE_NAMES[args.profile_name or "full"]
        resource = _packaged_profile_resource(filename)
        profile_display = _packaged_profile_display(filename)
        with as_file(resource) as profile_path:
            outstation = create_mesa_outstation(profile_path=profile_path, **outstation_kwargs)

    print(f"MESA Outstation starting on {args.host}:{args.port}")
    print(f"  Profile: {profile_display}")
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
