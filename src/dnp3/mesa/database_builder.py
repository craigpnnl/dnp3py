"""Build a dnp3py Database and AnalogOutputStore from a MESA profile.

Iterates over the four point sections in a :class:`Profile` and populates
a :class:`Database` (for BI, BO, AI) and an :class:`AnalogOutputStore`
(for AO).  All points are set to ONLINE quality on creation.
"""

from __future__ import annotations

from dnp3.core.flags import AnalogQuality, BinaryQuality
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    Database,
    DatabaseConfig,
)
from dnp3.mesa.ao_store import AnalogOutputStore, AnalogOutputValue
from dnp3.mesa.profile import PointType, Profile

# Headroom added to max index so DatabaseConfig limits are not too tight.
_HEADROOM = 10


def build_database(
    profile: Profile,
    excluded_indices: dict[PointType, set[int]] | None = None,
) -> tuple[Database, AnalogOutputStore]:
    """Build a dnp3py Database and AnalogOutputStore from a MESA profile.

    Only *supported* points (already filtered by :func:`load_profile`) are
    added.  Binary and analog input/output points go into the Database;
    analog output points go into the AnalogOutputStore.

    Args:
        profile: A fully loaded :class:`Profile`.
        excluded_indices: Optional dict mapping :class:`PointType` to a set
            of point indices that should be skipped.  Typically produced by
            :func:`~dnp3.mesa.entities.compute_excluded_indices`.

    Returns:
        A ``(Database, AnalogOutputStore)`` tuple.
    """
    if excluded_indices is None:
        excluded_indices = {}

    def _is_excluded(point_type: PointType, index: int) -> bool:
        return index in excluded_indices.get(point_type, set())

    bi_points = [p for p in profile.binary_inputs.points if not _is_excluded(p.point_type, p.index)]
    bo_points = [p for p in profile.binary_outputs.points if not _is_excluded(p.point_type, p.index)]
    ai_points = [p for p in profile.analog_inputs.points if not _is_excluded(p.point_type, p.index)]
    ao_points = [p for p in profile.analog_outputs.points if not _is_excluded(p.point_type, p.index)]

    # --- DatabaseConfig with enough room for the highest index ----------
    config = DatabaseConfig(
        max_binary_inputs=len(bi_points) + _HEADROOM,
        max_binary_outputs=len(bo_points) + _HEADROOM,
        max_analog_inputs=len(ai_points) + _HEADROOM,
    )
    database = Database(config=config)

    # --- Binary Inputs --------------------------------------------------
    for point in bi_points:
        database.add_binary_input(
            index=point.index,
            config=BinaryInputConfig(),
            value=bool(point.value),
            quality=BinaryQuality.ONLINE,
        )

    # --- Binary Outputs -------------------------------------------------
    for point in bo_points:
        database.add_binary_output(
            index=point.index,
            config=BinaryOutputConfig(),
            value=bool(point.value),
            quality=BinaryQuality.ONLINE,
        )

    # --- Analog Inputs --------------------------------------------------
    for point in ai_points:
        database.add_analog_input(
            index=point.index,
            config=AnalogInputConfig(deadband=0.0),
            value=float(point.value),
            quality=AnalogQuality.ONLINE,
        )

    # --- Analog Outputs (into store, not database) ----------------------
    ao_store = AnalogOutputStore()
    for point in ao_points:
        ao_store.add(
            AnalogOutputValue(
                index=point.index,
                value=float(point.value),
                minimum=float(point.minimum) if point.minimum is not None else 0.0,
                maximum=float(point.maximum) if point.maximum is not None else 0.0,
                multiplier=float(point.multiplier) if point.multiplier is not None else 1.0,
                offset=float(point.offset) if point.offset is not None else 0.0,
                units=point.units or "",
                description=point.description,
            )
        )

    return database, ao_store
