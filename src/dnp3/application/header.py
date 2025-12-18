"""Application Layer headers per IEEE 1815-2012 Clause 4.

Application Control byte layout:
- Bit 7: FIR (first fragment)
- Bit 6: FIN (final fragment)
- Bit 5: CON (confirm requested)
- Bit 4: UNS (unsolicited response)
- Bits 3-0: SEQ (sequence number, 0-15)

Request header: AC (1 byte) + FC (1 byte) = 2 bytes
Response header: AC (1 byte) + FC (1 byte) + IIN (2 bytes) = 4 bytes
"""

from dataclasses import dataclass

from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN

# Application control byte bit positions
_FIR_BIT = 0x80
_FIN_BIT = 0x40
_CON_BIT = 0x20
_UNS_BIT = 0x10
_SEQ_MASK = 0x0F

# Header sizes
REQUEST_HEADER_SIZE = 2
RESPONSE_HEADER_SIZE = 4

# Maximum sequence number
MAX_APP_SEQUENCE = 15


@dataclass(frozen=True, slots=True)
class ApplicationControl:
    """Application layer control byte.

    Attributes:
        fir: First fragment flag.
        fin: Final fragment flag.
        con: Confirmation requested flag.
        uns: Unsolicited response flag.
        seq: Sequence number (0-15).
    """

    fir: bool
    fin: bool
    con: bool
    uns: bool
    seq: int

    def __post_init__(self) -> None:
        """Validate sequence number range."""
        if not 0 <= self.seq <= MAX_APP_SEQUENCE:
            msg = f"Sequence number {self.seq} out of range (0-{MAX_APP_SEQUENCE})"
            raise ValueError(msg)

    def to_byte(self) -> int:
        """Serialize to single byte.

        Returns:
            8-bit application control value.
        """
        value = self.seq & _SEQ_MASK
        if self.fir:
            value |= _FIR_BIT
        if self.fin:
            value |= _FIN_BIT
        if self.con:
            value |= _CON_BIT
        if self.uns:
            value |= _UNS_BIT
        return value

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            1-byte application control.
        """
        return bytes([self.to_byte()])

    @classmethod
    def from_byte(cls, value: int) -> "ApplicationControl":
        """Parse from single byte.

        Args:
            value: 8-bit application control value.

        Returns:
            ApplicationControl instance.
        """
        return cls(
            fir=bool(value & _FIR_BIT),
            fin=bool(value & _FIN_BIT),
            con=bool(value & _CON_BIT),
            uns=bool(value & _UNS_BIT),
            seq=value & _SEQ_MASK,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "ApplicationControl":
        """Parse from bytes.

        Args:
            data: At least 1 byte of data.

        Returns:
            ApplicationControl instance.

        Raises:
            ValueError: If data is empty.
        """
        if not data:
            msg = "Cannot parse application control from empty data"
            raise ValueError(msg)
        return cls.from_byte(data[0])

    @property
    def is_first(self) -> bool:
        """Check if this is the first fragment."""
        return self.fir

    @property
    def is_final(self) -> bool:
        """Check if this is the final fragment."""
        return self.fin

    @property
    def is_only(self) -> bool:
        """Check if this is the only fragment (FIR and FIN both set)."""
        return self.fir and self.fin

    @property
    def confirms_requested(self) -> bool:
        """Check if confirmation is requested."""
        return self.con

    @property
    def is_unsolicited(self) -> bool:
        """Check if this is an unsolicited response."""
        return self.uns


@dataclass(frozen=True, slots=True)
class RequestHeader:
    """Application layer request header.

    A request consists of:
    - Application control (1 byte)
    - Function code (1 byte)

    Attributes:
        control: Application control byte.
        function: Function code.
    """

    control: ApplicationControl
    function: FunctionCode

    @classmethod
    def build(
        cls,
        function: FunctionCode,
        fir: bool = True,
        fin: bool = True,
        con: bool = False,
        seq: int = 0,
    ) -> "RequestHeader":
        """Build a request header from components.

        Args:
            function: Function code for the request.
            fir: First fragment flag.
            fin: Final fragment flag.
            con: Confirmation requested flag.
            seq: Sequence number (0-15).

        Returns:
            RequestHeader instance.
        """
        control = ApplicationControl(
            fir=fir,
            fin=fin,
            con=con,
            uns=False,  # UNS is not used in requests
            seq=seq,
        )
        return cls(control=control, function=function)

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            2-byte request header.
        """
        return bytes([self.control.to_byte(), self.function.value])

    @classmethod
    def from_bytes(cls, data: bytes) -> "RequestHeader":
        """Parse from bytes.

        Args:
            data: At least 2 bytes of data.

        Returns:
            RequestHeader instance.

        Raises:
            ValueError: If data is too short or function code is invalid.
        """
        if len(data) < REQUEST_HEADER_SIZE:
            msg = f"Request header requires {REQUEST_HEADER_SIZE} bytes, got {len(data)}"
            raise ValueError(msg)

        control = ApplicationControl.from_byte(data[0])
        try:
            function = FunctionCode(data[1])
        except ValueError:
            msg = f"Unknown function code: 0x{data[1]:02X}"
            raise ValueError(msg) from None

        return cls(control=control, function=function)


@dataclass(frozen=True, slots=True)
class ResponseHeader:
    """Application layer response header.

    A response consists of:
    - Application control (1 byte)
    - Function code (1 byte)
    - Internal indications (2 bytes)

    Attributes:
        control: Application control byte.
        function: Function code.
        iin: Internal indications.
    """

    control: ApplicationControl
    function: FunctionCode
    iin: IIN

    @classmethod
    def build(
        cls,
        function: FunctionCode,
        iin: IIN | None = None,
        fir: bool = True,
        fin: bool = True,
        con: bool = False,
        uns: bool = False,
        seq: int = 0,
    ) -> "ResponseHeader":
        """Build a response header from components.

        Args:
            function: Function code for the response.
            iin: Internal indications (defaults to no indications).
            fir: First fragment flag.
            fin: Final fragment flag.
            con: Confirmation requested flag.
            uns: Unsolicited response flag.
            seq: Sequence number (0-15).

        Returns:
            ResponseHeader instance.
        """
        if iin is None:
            iin = IIN(0)
        control = ApplicationControl(
            fir=fir,
            fin=fin,
            con=con,
            uns=uns,
            seq=seq,
        )
        return cls(control=control, function=function, iin=iin)

    def to_bytes(self) -> bytes:
        """Serialize to bytes.

        Returns:
            4-byte response header.
        """
        iin_bytes = self.iin.to_bytes()
        return bytes([self.control.to_byte(), self.function.value]) + iin_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "ResponseHeader":
        """Parse from bytes.

        Args:
            data: At least 4 bytes of data.

        Returns:
            ResponseHeader instance.

        Raises:
            ValueError: If data is too short or function code is invalid.
        """
        if len(data) < RESPONSE_HEADER_SIZE:
            msg = f"Response header requires {RESPONSE_HEADER_SIZE} bytes, got {len(data)}"
            raise ValueError(msg)

        control = ApplicationControl.from_byte(data[0])
        try:
            function = FunctionCode(data[1])
        except ValueError:
            msg = f"Unknown function code: 0x{data[1]:02X}"
            raise ValueError(msg) from None

        iin = IIN.from_bytes(data[2:4])
        return cls(control=control, function=function, iin=iin)

    @property
    def has_events(self) -> bool:
        """Check if any class events are pending."""
        return bool(self.iin & (IIN.CLASS_1_EVENTS | IIN.CLASS_2_EVENTS | IIN.CLASS_3_EVENTS))

    @property
    def needs_time(self) -> bool:
        """Check if time synchronization is needed."""
        return bool(self.iin & IIN.NEED_TIME)

    @property
    def device_restart(self) -> bool:
        """Check if device has restarted."""
        return bool(self.iin & IIN.DEVICE_RESTART)
