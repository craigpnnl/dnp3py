"""MESA command handler for DNP3 outstation control operations.

Handles binary and analog output commands, updating the database
and AO store according to MESA profile semantics.
"""

from __future__ import annotations

from dnp3.core.enums import ControlCode
from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.profile import PointType
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler

__all__ = ["MesaCommandHandler"]


class MesaCommandHandler(DefaultCommandHandler):
    """Command handler that applies MESA profile semantics.

    Binary outputs are written directly to the database.
    Analog outputs are validated against the AO store range,
    persisted to the store, and mirrored to associated AI points.
    """

    def __init__(
        self,
        database: Database,
        ao_store: AnalogOutputStore,
        associated_indices: dict[int, tuple[str, int]] | None = None,
    ) -> None:
        super().__init__()
        self._database = database
        self._ao_store = ao_store
        # Values are (PointType.value string, target_index).  The string form
        # is kept so the dict type stays serialisation-friendly; comparisons
        # use the enum's .value to avoid bare-string magic.
        self._associated_indices: dict[int, tuple[str, int]] = associated_indices or {}

    # -- Binary output helpers ------------------------------------------------

    def _validate_binary_output(self, index: int) -> CommandResult | None:
        """Return an error result if the BO index does not exist, else None."""
        if self._database.get_binary_output(index) is None:
            return CommandResult.not_supported(f"Binary output {index} not found")
        return None

    def _execute_binary_output(self, index: int, code: ControlCode) -> CommandResult:
        """Validate and apply a binary output command."""
        err = self._validate_binary_output(index)
        if err is not None:
            return err

        if code == ControlCode.LATCH_ON:
            self._database.update_binary_output(index, value=True)
        elif code == ControlCode.LATCH_OFF:
            self._database.update_binary_output(index, value=False)

        return CommandResult.success()

    # -- Binary output overrides ----------------------------------------------

    def select_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Validate that the binary output exists (no execution)."""
        err = self._validate_binary_output(index)
        if err is not None:
            return err
        return CommandResult.success()

    def operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
        select_sequence: int,
    ) -> CommandResult:
        """Execute a binary output command after prior SELECT."""
        return self._execute_binary_output(index, code)

    def direct_operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Execute a binary output command without prior SELECT."""
        return self._execute_binary_output(index, code)

    # -- Analog output helpers ------------------------------------------------

    def _validate_analog_output(self, index: int, value: float) -> CommandResult | None:
        """Return an error result if the AO index is missing or value out of range."""
        ao = self._ao_store.get(index)
        if ao is None:
            return CommandResult.not_supported(f"Analog output {index} not found")
        if value < ao.minimum or value > ao.maximum:
            return CommandResult.out_of_range(f"Value {value} outside [{ao.minimum}, {ao.maximum}]")
        return None

    def _execute_analog_output(self, index: int, value: float) -> CommandResult:
        """Validate, persist to AO store, and mirror to associated AI."""
        err = self._validate_analog_output(index, value)
        if err is not None:
            return err

        self._ao_store.set_value(index, value)

        assoc = self._associated_indices.get(index)
        if assoc is not None:
            point_type, ai_index = assoc
            if point_type == PointType.ANALOG_INPUT.value:
                self._database.update_analog_input(ai_index, value)

        return CommandResult.success()

    # -- Analog output overrides ----------------------------------------------

    def select_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Validate the analog output (no store update)."""
        err = self._validate_analog_output(index, value)
        if err is not None:
            return err
        return CommandResult.success()

    def operate_analog_output(
        self,
        index: int,
        value: float,
        select_sequence: int,
    ) -> CommandResult:
        """Execute an analog output command after prior SELECT."""
        return self._execute_analog_output(index, value)

    def direct_operate_analog_output(
        self,
        index: int,
        value: float,
    ) -> CommandResult:
        """Execute an analog output command without prior SELECT."""
        return self._execute_analog_output(index, value)
