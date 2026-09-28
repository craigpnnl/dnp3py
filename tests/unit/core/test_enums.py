"""Tests for protocol enumerations."""

import importlib
import pickle
import pkgutil
import sys

import pytest

import dnp3
from dnp3.core.enums import (
    CommandStatus,
    ControlCode,
    FunctionCode,
    LinkFunctionCode,
    OperationType,
    QualifierCode,
    TripCloseCode,
)


class TestFunctionCode:
    """Tests for application layer function codes."""

    def test_read_value(self) -> None:
        """READ function code is 0x01."""
        assert FunctionCode.READ == 0x01

    def test_write_value(self) -> None:
        """WRITE function code is 0x02."""
        assert FunctionCode.WRITE == 0x02

    def test_select_value(self) -> None:
        """SELECT function code is 0x03."""
        assert FunctionCode.SELECT == 0x03

    def test_operate_value(self) -> None:
        """OPERATE function code is 0x04."""
        assert FunctionCode.OPERATE == 0x04

    def test_direct_operate_value(self) -> None:
        """DIRECT_OPERATE function code is 0x05."""
        assert FunctionCode.DIRECT_OPERATE == 0x05

    def test_response_value(self) -> None:
        """RESPONSE function code is 0x81."""
        assert FunctionCode.RESPONSE == 0x81

    def test_unsolicited_response_value(self) -> None:
        """UNSOLICITED_RESPONSE function code is 0x82."""
        assert FunctionCode.UNSOLICITED_RESPONSE == 0x82

    def test_is_response(self) -> None:
        """Check if function code is a response."""
        assert FunctionCode.RESPONSE.is_response()
        assert FunctionCode.UNSOLICITED_RESPONSE.is_response()
        assert not FunctionCode.READ.is_response()

    def test_from_int(self) -> None:
        """Create FunctionCode from integer."""
        fc = FunctionCode(0x01)
        assert fc == FunctionCode.READ


class TestLinkFunctionCode:
    """Tests for data link layer function codes."""

    def test_primary_reset_link(self) -> None:
        """Primary RESET_LINK_STATE is 0."""
        assert LinkFunctionCode.PRI_RESET_LINK_STATE == 0

    def test_primary_user_data(self) -> None:
        """Primary USER_DATA is 3."""
        assert LinkFunctionCode.PRI_CONFIRMED_USER_DATA == 3

    def test_primary_unconfirmed_data(self) -> None:
        """Primary UNCONFIRMED_USER_DATA is 4."""
        assert LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA == 4

    def test_secondary_ack(self) -> None:
        """Secondary ACK is 0."""
        assert LinkFunctionCode.SEC_ACK == 0

    def test_secondary_nack(self) -> None:
        """Secondary NACK is 1."""
        assert LinkFunctionCode.SEC_NACK == 1


class TestQualifierCode:
    """Tests for object header qualifier codes."""

    def test_start_stop_8bit(self) -> None:
        """8-bit start-stop qualifier is 0x00."""
        assert QualifierCode.UINT8_START_STOP == 0x00

    def test_start_stop_16bit(self) -> None:
        """16-bit start-stop qualifier is 0x01."""
        assert QualifierCode.UINT16_START_STOP == 0x01

    def test_count_8bit(self) -> None:
        """8-bit count qualifier is 0x07."""
        assert QualifierCode.UINT8_COUNT == 0x07

    def test_count_16bit(self) -> None:
        """16-bit count qualifier is 0x08."""
        assert QualifierCode.UINT16_COUNT == 0x08

    def test_all_objects(self) -> None:
        """ALL_OBJECTS qualifier is 0x06."""
        assert QualifierCode.ALL_OBJECTS == 0x06


class TestCommandStatus:
    """Tests for control command status codes."""

    def test_success(self) -> None:
        """SUCCESS status is 0."""
        assert CommandStatus.SUCCESS == 0

    def test_timeout(self) -> None:
        """TIMEOUT status is 1."""
        assert CommandStatus.TIMEOUT == 1

    def test_not_supported(self) -> None:
        """NOT_SUPPORTED status is 4."""
        assert CommandStatus.NOT_SUPPORTED == 4

    def test_is_success(self) -> None:
        """Check if status indicates success."""
        assert CommandStatus.SUCCESS.is_success()
        assert not CommandStatus.TIMEOUT.is_success()


# IEEE 1815-2012 Table A-2 rows: (octet, TCC, Op Type, Clear). Queue is 0 in every row.
TABLE_A2_ROWS = [
    (0x00, TripCloseCode.NUL, OperationType.NUL, False),
    (0x20, TripCloseCode.NUL, OperationType.NUL, True),
    (0x01, TripCloseCode.NUL, OperationType.PULSE_ON, False),
    (0x21, TripCloseCode.NUL, OperationType.PULSE_ON, True),
    (0x03, TripCloseCode.NUL, OperationType.LATCH_ON, False),
    (0x23, TripCloseCode.NUL, OperationType.LATCH_ON, True),
    (0x04, TripCloseCode.NUL, OperationType.LATCH_OFF, False),
    (0x24, TripCloseCode.NUL, OperationType.LATCH_OFF, True),
    (0x41, TripCloseCode.CLOSE, OperationType.PULSE_ON, False),
    (0x61, TripCloseCode.CLOSE, OperationType.PULSE_ON, True),
    (0x81, TripCloseCode.TRIP, OperationType.PULSE_ON, False),
    (0xA1, TripCloseCode.TRIP, OperationType.PULSE_ON, True),
]


class TestControlCodeTableA2:
    """g12v1 control-code octet decode and encode against IEEE 1815-2012 Table A-2."""

    @pytest.mark.parametrize(("octet", "tcc", "op_type", "clear"), TABLE_A2_ROWS)
    def test_decode_fields(self, octet: int, tcc: TripCloseCode, op_type: OperationType, clear: bool) -> None:
        """Each interoperable octet decodes to the TCC, Clear, Queue and Op Type the table gives."""
        code = ControlCode(octet)
        assert code.tcc is tcc
        assert code.op_type is op_type
        assert code.clear is clear
        assert code.queue is False

    @pytest.mark.parametrize(("octet", "tcc", "op_type", "clear"), TABLE_A2_ROWS)
    def test_round_trip(self, octet: int, tcc: TripCloseCode, op_type: OperationType, clear: bool) -> None:
        """encode(decode(octet)) == octet, and encoding the table's fields yields the octet."""
        assert int(ControlCode(octet)) == octet
        encoded = ControlCode.from_fields(op_type, tcc=tcc, clear=clear)
        assert int(encoded) == octet
        assert encoded == ControlCode(octet)

    def test_trip_and_close_decode_apart(self) -> None:
        """0x81 is TRIP + PULSE_ON, 0x41 is CLOSE + PULSE_ON, and they are not equal."""
        trip = ControlCode(0x81)
        close = ControlCode(0x41)
        assert trip.tcc is TripCloseCode.TRIP
        assert close.tcc is TripCloseCode.CLOSE
        assert trip.op_type is OperationType.PULSE_ON
        assert close.op_type is OperationType.PULSE_ON
        assert trip != close
        assert trip == ControlCode.TRIP_PULSE_ON
        assert close == ControlCode.CLOSE_PULSE_ON

    def test_bit_positions(self) -> None:
        """TCC is bits 7-6, Clear bit 5, Queue bit 4, Op Type bits 3-0 (A.8.1.2)."""
        assert int(ControlCode.from_fields(OperationType.NUL, tcc=TripCloseCode.RESERVED)) == 0xC0
        assert int(ControlCode.from_fields(OperationType.NUL, clear=True)) == 0x20
        assert int(ControlCode.from_fields(OperationType.NUL, queue=True)) == 0x10
        assert int(ControlCode.from_fields(OperationType.LATCH_OFF)) == 0x04

    def test_queue_bit_decodes(self) -> None:
        """A set Queue bit is carried, not dropped, so an outstation can reject it."""
        code = ControlCode(0x13)
        assert code.queue is True
        assert code.op_type is OperationType.LATCH_ON
        assert code.clear is False
        assert code.tcc is TripCloseCode.NUL

    def test_every_octet_round_trips_or_is_rejected(self) -> None:
        """All 256 octets: Op Type 0-4 round-trips field by field, Op Type 5-15 raises ValueError."""
        for octet in range(256):
            op_nibble = octet & 0x0F
            if op_nibble > OperationType.LATCH_OFF:
                with pytest.raises(ValueError, match="Op Type"):
                    ControlCode(octet)
                continue
            code = ControlCode(octet)
            assert int(code) == octet
            assert code.op_type == op_nibble
            assert code.queue is bool(octet & 0x10)
            assert code.clear is bool(octet & 0x20)
            assert code.tcc == octet >> 6
            assert ControlCode.from_fields(code.op_type, tcc=code.tcc, clear=code.clear, queue=code.queue) == code

    @pytest.mark.parametrize("value", [-1, 0x100])
    def test_out_of_range_rejected(self, value: int) -> None:
        """A value that is not one octet is rejected."""
        with pytest.raises(ValueError, match="octet"):
            ControlCode(value)

    def test_named_constants(self) -> None:
        """Named constants keep their whole-octet wire values."""
        assert ControlCode.NUL == 0x00
        assert ControlCode.PULSE_ON == 0x01
        assert ControlCode.PULSE_OFF == 0x02
        assert ControlCode.LATCH_ON == 0x03
        assert ControlCode.LATCH_OFF == 0x04
        assert ControlCode.CLOSE_PULSE_ON == 0x41
        assert ControlCode.TRIP_PULSE_ON == 0x81
        assert isinstance(ControlCode.LATCH_ON, ControlCode)
        assert ControlCode.LATCH_ON.name == "LATCH_ON"
        assert ControlCode(0xA1).name == "TRIP_PULSE_ON|CLEAR"


_NAMED_CONSTANTS = [
    ("NUL", 0x00, TripCloseCode.NUL, OperationType.NUL),
    ("PULSE_ON", 0x01, TripCloseCode.NUL, OperationType.PULSE_ON),
    ("PULSE_OFF", 0x02, TripCloseCode.NUL, OperationType.PULSE_OFF),
    ("LATCH_ON", 0x03, TripCloseCode.NUL, OperationType.LATCH_ON),
    ("LATCH_OFF", 0x04, TripCloseCode.NUL, OperationType.LATCH_OFF),
    ("CLOSE_PULSE_ON", 0x41, TripCloseCode.CLOSE, OperationType.PULSE_ON),
    ("TRIP_PULSE_ON", 0x81, TripCloseCode.TRIP, OperationType.PULSE_ON),
]


class TestControlCodeKeptSurface:
    """The parts of the former IntEnum surface that ControlCode keeps."""

    @pytest.mark.parametrize(("name", "octet", "tcc", "op_type"), _NAMED_CONSTANTS)
    def test_named_constant(self, name: str, octet: int, tcc: TripCloseCode, op_type: OperationType) -> None:
        """Attribute access, int value, .value, .name, repr and fields of each named constant."""
        code = getattr(ControlCode, name)
        assert type(code) is ControlCode
        assert isinstance(code, int)
        assert int(code) == octet
        assert code == octet
        assert code.value == octet
        assert type(code.value) is int
        assert code.name == name
        assert repr(code) == f"<ControlCode.{name}: 0x{octet:02X}>"
        assert code.tcc is tcc
        assert code.op_type is op_type
        assert code.clear is False
        assert code.queue is False

    @pytest.mark.parametrize(
        ("octet", "name"),
        [
            (0x13, "LATCH_ON|QUEUE"),
            (0x23, "LATCH_ON|CLEAR"),
            (0x33, "LATCH_ON|QUEUE|CLEAR"),
            (0xA1, "TRIP_PULSE_ON|CLEAR"),
            (0xC3, "RESERVED_LATCH_ON"),
            (0x44, "CLOSE_LATCH_OFF"),
        ],
    )
    def test_composite_name_and_repr(self, octet: int, name: str) -> None:
        """Codes without a constant get a name built from their fields."""
        code = ControlCode(octet)
        assert code.name == name
        assert code.value == octet
        assert repr(code) == f"<ControlCode.{name}: 0x{octet:02X}>"

    @pytest.mark.parametrize("octet", [0x00, 0x03, 0x41, 0x81, 0xA1, 0x13])
    def test_pickle_round_trip(self, octet: int) -> None:
        """A pickled code comes back as the same ControlCode with the same fields."""
        code = ControlCode(octet)
        restored = pickle.loads(pickle.dumps(code))
        assert type(restored) is ControlCode
        assert restored == code
        assert int(restored) == octet
        assert restored.tcc is code.tcc
        assert restored.clear is code.clear

    def test_hashes_and_compares_as_its_octet(self) -> None:
        """Dict lookups keyed by int octets find a ControlCode and the reverse."""
        assert hash(ControlCode.LATCH_ON) == hash(0x03)
        assert {0x03: "on"}[ControlCode.LATCH_ON] == "on"
        assert {ControlCode.TRIP_PULSE_ON: "trip"}[0x81] == "trip"
        assert bytes([ControlCode.TRIP_PULSE_ON]) == b"\x81"


class TestControlCodeFromFieldsRange:
    """from_fields rejects field values that would spill into neighbouring bits."""

    @pytest.mark.parametrize("op_type", [-1, 5, 15, 16, 0x41])
    def test_op_type_out_of_range(self, op_type: int) -> None:
        with pytest.raises(ValueError, match=r"Op Type .* out of range"):
            ControlCode.from_fields(op_type)  # type: ignore[arg-type]

    @pytest.mark.parametrize("tcc", [-1, 4, 255])
    def test_tcc_out_of_range(self, tcc: int) -> None:
        with pytest.raises(ValueError, match=r"Trip-Close code .* out of range"):
            ControlCode.from_fields(OperationType.NUL, tcc=tcc)  # type: ignore[arg-type]

    def test_bounds_accepted(self) -> None:
        """The largest valid field values still encode."""
        code = ControlCode.from_fields(OperationType.LATCH_OFF, tcc=TripCloseCode.RESERVED, clear=True, queue=True)
        assert int(code) == 0xF4


def test_control_code_field_types_exported_from_core() -> None:
    """Callers of ControlCode.from_fields can import its field types from dnp3.core."""
    import dnp3.core

    assert dnp3.core.OperationType is OperationType
    assert dnp3.core.TripCloseCode is TripCloseCode
    assert {"ControlCode", "OperationType", "TripCloseCode"} <= set(dnp3.core.__all__)
    code = dnp3.core.ControlCode.from_fields(dnp3.core.OperationType.PULSE_ON, tcc=dnp3.core.TripCloseCode.TRIP)
    assert code == dnp3.core.ControlCode.TRIP_PULSE_ON


def test_exactly_one_control_code_symbol() -> None:
    """Every module in the package that exposes ControlCode exposes the same class."""
    # One directory level of the package, then every dnp3 module that import pulled in.
    for info in pkgutil.iter_modules(dnp3.__path__, prefix="dnp3."):
        importlib.import_module(info.name)
    found = {
        name: module.ControlCode
        for name, module in list(sys.modules.items())
        if (name == "dnp3" or name.startswith("dnp3.")) and hasattr(module, "ControlCode")
    }
    assert "dnp3.core.enums" in found
    assert "dnp3.objects.binary_output" in found
    distinct = {id(cls) for cls in found.values()}
    assert len(distinct) == 1, f"ControlCode resolves to {len(distinct)} classes: {found}"
