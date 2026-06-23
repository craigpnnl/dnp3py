"""MESA IEEE 1815.2 outstation factory and runner.

Provides a factory function to create a fully wired MESA outstation
from a profile JSON file, and a dataclass to hold all the components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.entities import Entity, build_entities, compute_excluded_indices
from dnp3.mesa.profile import Profile, load_profile, parse_index
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.tcp_runner import OutstationTcpRunner


@dataclass
class MesaOutstation:
    """MESA IEEE 1815.2 outstation simulator loaded from a PICS profile."""

    profile: Profile
    database: Database
    ao_store: AnalogOutputStore
    entities: list[Entity]
    outstation: Outstation
    handler: MesaCommandHandler
    host: str = "0.0.0.0"
    port: int = 20000

    _runner: OutstationTcpRunner | None = field(default=None, init=False, repr=False)

    async def run(self) -> None:
        """Start TCP server and process incoming requests."""
        self._runner = OutstationTcpRunner(
            outstation=self.outstation,
            host=self.host,
            port=self.port,
        )
        await self._runner.run()

    async def stop(self) -> None:
        """Stop the outstation."""
        if self._runner is not None:
            await self._runner.stop()

    @property
    def is_running(self) -> bool:
        """Check if the TCP server is running."""
        return self._runner is not None and self._runner.is_running

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Get the local address the server is bound to."""
        if self._runner is not None:
            return self._runner.local_address
        return None


def _build_associated_indices(
    profile: Profile,
) -> dict[int, tuple[str, int]]:
    """Build AO index -> (point_type_prefix, target_index) mapping.

    Iterates analog output profile points that have an ``associated_index``
    field (e.g. ``"AI0"``), parses it, and stores the mapping so that
    the command handler can mirror AO writes to the associated point.
    """
    associated: dict[int, tuple[str, int]] = {}
    for point in profile.analog_outputs.points:
        if point.associated_index is not None:
            point_type, target_index = parse_index(point.associated_index)
            associated[point.index] = (point_type.value, target_index)
    return associated


def create_mesa_outstation(
    profile_path: Path,
    host: str = "0.0.0.0",
    port: int = 20000,
    address: int = 1,
    master_address: int = 0,
    entity_overrides: dict[str, int] | None = None,
) -> MesaOutstation:
    """Factory function to create a fully wired MESA outstation.

    Args:
        profile_path: Path to the MESA profile JSON file.
        host: TCP listen address.
        port: TCP listen port.
        address: DNP3 outstation address.
        master_address: Expected DNP3 master address.
        entity_overrides: Optional dict to override entity counts
            (e.g. ``{"meters": 0}`` to exclude meters).

    Returns:
        A fully constructed :class:`MesaOutstation`.
    """
    # 1. Load profile
    profile = load_profile(profile_path)

    # 2. Compute excluded indices from entity overrides
    excluded = compute_excluded_indices(profile, entity_overrides)

    # 3. Build database and AO store (excluding overridden entity points)
    database, ao_store = build_database(profile, excluded)

    # 4. Build entities
    entities = build_entities(profile, entity_overrides)

    # 5. Build associated indices mapping
    associated_indices = _build_associated_indices(profile)

    # 6. Create command handler
    handler = MesaCommandHandler(
        database=database,
        ao_store=ao_store,
        associated_indices=associated_indices,
    )

    # 7. Create outstation config
    config = OutstationConfig(
        address=address,
        master_address=master_address,
    )

    # 8. Create outstation
    outstation = Outstation(
        config=config,
        database=database,
        handler=handler,
    )

    return MesaOutstation(
        profile=profile,
        database=database,
        ao_store=ao_store,
        entities=entities,
        outstation=outstation,
        handler=handler,
        host=host,
        port=port,
    )
