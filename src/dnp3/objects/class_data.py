"""Class Data objects per IEEE 1815-2012.

Group 60: Class Data
- Variation 1: Class 0 data (static data)
- Variation 2: Class 1 events
- Variation 3: Class 2 events
- Variation 4: Class 3 events

These objects are used in READ requests to request data by class.
They have no data content - they are identifiers only.
"""

from dataclasses import dataclass
from typing import ClassVar

from dnp3.objects.base import StaticObject
from dnp3.objects.registry import register

# Group number
CLASS_DATA_GROUP = 60


@register
@dataclass(frozen=True, slots=True)
class ClassData0(StaticObject):
    """Class 0 Data request (g60v1).

    Used to request all static (current) data.
    Has no data content - object header only.
    """

    GROUP: ClassVar[int] = CLASS_DATA_GROUP
    VARIATION: ClassVar[int] = 1
    SIZE: ClassVar[int] = 0  # No data content

    def to_bytes(self) -> bytes:
        """No data content."""
        return b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "ClassData0":
        """Parse (no data content)."""
        return cls()


@register
@dataclass(frozen=True, slots=True)
class ClassData1(StaticObject):
    """Class 1 Data request (g60v2).

    Used to request Class 1 events.
    Has no data content - object header only.
    """

    GROUP: ClassVar[int] = CLASS_DATA_GROUP
    VARIATION: ClassVar[int] = 2
    SIZE: ClassVar[int] = 0

    def to_bytes(self) -> bytes:
        """No data content."""
        return b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "ClassData1":
        """Parse (no data content)."""
        return cls()


@register
@dataclass(frozen=True, slots=True)
class ClassData2(StaticObject):
    """Class 2 Data request (g60v3).

    Used to request Class 2 events.
    Has no data content - object header only.
    """

    GROUP: ClassVar[int] = CLASS_DATA_GROUP
    VARIATION: ClassVar[int] = 3
    SIZE: ClassVar[int] = 0

    def to_bytes(self) -> bytes:
        """No data content."""
        return b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "ClassData2":
        """Parse (no data content)."""
        return cls()


@register
@dataclass(frozen=True, slots=True)
class ClassData3(StaticObject):
    """Class 3 Data request (g60v4).

    Used to request Class 3 events.
    Has no data content - object header only.
    """

    GROUP: ClassVar[int] = CLASS_DATA_GROUP
    VARIATION: ClassVar[int] = 4
    SIZE: ClassVar[int] = 0

    def to_bytes(self) -> bytes:
        """No data content."""
        return b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "ClassData3":
        """Parse (no data content)."""
        return cls()
