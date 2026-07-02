"""MESA IEEE 1815.2 outstation factory and runner.

Provides a factory function to create a fully wired MESA outstation
from a profile JSON file, and a dataclass to hold all the components.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.command_handler import MesaCommandHandler
from dnp3.mesa.database_builder import build_database
from dnp3.mesa.entities import Entity, build_entities, compute_excluded_indices
from dnp3.mesa.profile import PicsProfile, PointType, load_profile, parse_assoc_index
from dnp3.outstation import Outstation, OutstationConfig
from dnp3.outstation.tcp_runner import OutstationTcpRunner

__all__ = ["MesaOutstation", "create_mesa_outstation"]

_log = logging.getLogger(__name__)


@dataclass  # mutable: _runner is set on first call to run() after construction
class MesaOutstation:
    """MESA IEEE 1815.2 outstation simulator loaded from a PICS profile."""

    profile: PicsProfile
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
    profile: PicsProfile,
    database: Database,
    excluded_indices: dict[PointType, set[int]] | None = None,
) -> dict[int, tuple[str, int]]:
    """Build AO index -> (point_type_prefix, target_index) mapping.

    Iterates analog output points that carry an ``assoc_ai`` field (e.g.
    ``"AI29"``), parses it, and stores the mapping so the command handler can
    mirror AO writes to the associated point.

    When entity overrides exclude an AO (and its associated AI), the pair is
    silently skipped rather than raising: the exclusion is intentional. If an AO
    *is* in the database but its associated AI is not, that is a stale profile
    reference and a ``ValueError`` is raised.

    Note: this reads the plain AO -> AI association only. The multiplexed
    curve/schedule selector association is a later-PR concern; a selector AO
    whose target AI lives in a curve/schedule sub-group is skipped when its
    target is not a base AI in the database.

    Args:
        profile: Fully loaded profile.
        database: Already-built database; used to validate that every included
            AO's associated AI target exists.
        excluded_indices: Same exclusion set passed to ``build_database``, so
            intentionally omitted AOs are skipped.

    Raises:
        ValueError: If ``assoc_ai`` is malformed.
    """
    excluded = excluded_indices or {}
    excluded_ao: set[int] = excluded.get(PointType.ANALOG_OUTPUT, set())

    associated: dict[int, tuple[str, int]] = {}
    for point in profile.ao.all_points():
        if point.assoc_ai is None:
            continue
        if point.point_index in excluded_ao:
            # Intentionally excluded by entity overrides; target may be absent.
            continue
        try:
            point_type, target_index = parse_assoc_index(point.assoc_ai)
        except ValueError as exc:
            msg = f"AO{point.point_index}: malformed assoc_ai {point.assoc_ai!r}: {exc}"
            raise ValueError(msg) from exc

        if point_type is PointType.ANALOG_INPUT and database.get_analog_input(target_index) is None:
            # The target AI is not a base point in the database (it lives in a
            # curve/schedule sub-group whose multiplexed wiring is a later PR).
            # Skip the plain-mirror association for it rather than failing.
            _log.debug(
                "AO%d: assoc_ai target AI%d is not a base database index "
                "(curve/schedule selector; mirror deferred to PR3)",
                point.point_index,
                target_index,
            )
            continue

        # Store the PointType enum value string so the command handler can
        # compare via PointType.ANALOG_INPUT.value (no bare "AI" magic).
        associated[point.point_index] = (point_type.value, target_index)
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

    # 5. Build associated indices mapping (validates targets against database)
    associated_indices = _build_associated_indices(profile, database, excluded)

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
