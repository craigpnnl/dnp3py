"""Object registry for DNP3 group/variation lookup.

The registry provides a central place to register and lookup object types
by their group and variation numbers.
"""

from typing import TypeVar

from dnp3.objects.base import DNP3Object, GroupVariation

T = TypeVar("T", bound=DNP3Object)

# Global registry mapping (group, variation) to object class
_REGISTRY: dict[tuple[int, int], type[DNP3Object]] = {}


def register(cls: type[T]) -> type[T]:
    """Decorator to register an object class.

    Usage:
        @register
        class BinaryInputPackedFormat(StaticObject):
            GROUP = 1
            VARIATION = 1
            ...

    Args:
        cls: The object class to register.

    Returns:
        The same class (allows use as decorator).

    Raises:
        ValueError: If GROUP or VARIATION is not defined, or if already registered.
    """
    if not hasattr(cls, "GROUP") or not hasattr(cls, "VARIATION"):
        msg = f"Class {cls.__name__} must define GROUP and VARIATION"
        raise ValueError(msg)

    key = (cls.GROUP, cls.VARIATION)
    if key in _REGISTRY:
        existing = _REGISTRY[key]
        msg = f"Group {cls.GROUP} Variation {cls.VARIATION} already registered to {existing.__name__}"
        raise ValueError(msg)

    _REGISTRY[key] = cls
    return cls


def lookup(group: int, variation: int) -> type[DNP3Object] | None:
    """Look up an object class by group and variation.

    Args:
        group: Object group number.
        variation: Object variation number.

    Returns:
        The registered object class, or None if not found.
    """
    return _REGISTRY.get((group, variation))


def lookup_gv(gv: GroupVariation) -> type[DNP3Object] | None:
    """Look up an object class by GroupVariation.

    Args:
        gv: GroupVariation identifier.

    Returns:
        The registered object class, or None if not found.
    """
    return _REGISTRY.get((gv.group, gv.variation))


def get_registered() -> list[tuple[int, int]]:
    """Get all registered group/variation pairs.

    Returns:
        List of (group, variation) tuples, sorted.
    """
    return sorted(_REGISTRY.keys())


def get_size(group: int, variation: int) -> int | None:
    """Get the size of an object type.

    Args:
        group: Object group number.
        variation: Object variation number.

    Returns:
        Size in bytes, or None if not registered or variable size.
    """
    cls = lookup(group, variation)
    if cls is None:
        return None
    return cls.size()


def is_registered(group: int, variation: int) -> bool:
    """Check if a group/variation is registered.

    Args:
        group: Object group number.
        variation: Object variation number.

    Returns:
        True if registered, False otherwise.
    """
    return (group, variation) in _REGISTRY


def clear_registry() -> None:
    """Clear all registrations (for testing)."""
    _REGISTRY.clear()


def get_registry_copy() -> dict[tuple[int, int], type[DNP3Object]]:
    """Get a copy of the registry (for testing/inspection).

    Returns:
        Copy of the registry dictionary.
    """
    return dict(_REGISTRY)
