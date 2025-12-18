"""Data Link Control Byte per IEEE 1815-2012 Clause 9.2.4.

Control byte bit layout:
- Bit 7: DIR (direction: 1=from master, 0=from outstation)
- Bit 6: PRM (primary: 1=primary message, 0=secondary message)
- Bit 5: FCB (frame count bit)
- Bit 4: FCV (frame count valid)
- Bits 3-0: Function code
"""

from dataclasses import dataclass

# Bit positions
_DIR_BIT = 0x80
_PRM_BIT = 0x40
_FCB_BIT = 0x20
_FCV_BIT = 0x10
_FUNC_MASK = 0x0F


@dataclass(frozen=True, slots=True)
class ControlByte:
    """Data link control byte.

    Attributes:
        dir_from_master: Direction bit (True if from master station)
        prm: Primary bit (True if primary message)
        fcb: Frame count bit
        fcv: Frame count valid bit
        function_code: 4-bit function code (0-15)
    """

    dir_from_master: bool
    prm: bool
    fcb: bool
    fcv: bool
    function_code: int

    def to_int(self) -> int:
        """Serialize to single byte.

        Returns:
            8-bit control byte value.
        """
        value = self.function_code & _FUNC_MASK
        if self.dir_from_master:
            value |= _DIR_BIT
        if self.prm:
            value |= _PRM_BIT
        if self.fcb:
            value |= _FCB_BIT
        if self.fcv:
            value |= _FCV_BIT
        return value

    @classmethod
    def from_int(cls, value: int) -> "ControlByte":
        """Parse from single byte.

        Args:
            value: 8-bit control byte value.

        Returns:
            ControlByte instance.
        """
        return cls(
            dir_from_master=bool(value & _DIR_BIT),
            prm=bool(value & _PRM_BIT),
            fcb=bool(value & _FCB_BIT),
            fcv=bool(value & _FCV_BIT),
            function_code=value & _FUNC_MASK,
        )

    @property
    def is_from_master(self) -> bool:
        """Check if message is from master station."""
        return self.dir_from_master

    @property
    def is_primary(self) -> bool:
        """Check if this is a primary message."""
        return self.prm
