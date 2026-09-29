"""MESA command handler for DNP3 outstation control operations.

Handles binary and analog output commands, updating the database
and AO store according to MESA profile semantics.
"""

from __future__ import annotations

import math

from dnp3.core.enums import ControlCode
from dnp3.database import Database
from dnp3.mesa.ao_store import AnalogOutputStore
from dnp3.mesa.profile import PointType
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler

__all__ = ["MesaCommandHandler"]

# IEEE 1815.2-2025 5.6.2: every binary output behaves as latched and pulse times
# are ignored. Value is the latched state a code sets; None means no change.
# A code absent from this map is not carried out and gets NOT_SUPPORTED.
_LATCH_STATE: dict[int, bool | None] = {
    ControlCode.NUL: None,
    ControlCode.LATCH_ON: True,
    ControlCode.PULSE_ON: True,
    ControlCode.CLOSE_PULSE_ON: True,
    ControlCode.LATCH_OFF: False,
    ControlCode.PULSE_OFF: False,
    ControlCode.TRIP_PULSE_ON: False,
}


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

    def _check_binary_output(self, index: int, code: ControlCode, count: int) -> CommandResult | None:
        """Return an error result if the command would be refused, else None.

        SELECT and OPERATE share this check so a SELECT is refused exactly
        when the OPERATE would be.
        """
        err = self._validate_binary_output(index)
        if err is not None:
            return err
        if code not in _LATCH_STATE:
            return CommandResult.not_supported(f"Control code 0x{int(code):02X} not supported")
        # Count 0 is a no-op that reports the status execution would get (IEEE 1815-2012 A.8.1.2.2).
        if count > 1:
            return CommandResult.not_supported(f"Count {count} not supported")
        return None

    def _execute_binary_output(self, index: int, code: ControlCode, count: int) -> CommandResult:
        """Validate and apply a binary output command."""
        err = self._check_binary_output(index, code, count)
        if err is not None:
            return err

        state = _LATCH_STATE[code]
        if state is not None and count == 1:
            self._database.update_binary_output(index, value=state)

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
        """Validate the command without executing it."""
        err = self._check_binary_output(index, code, count)
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
        return self._execute_binary_output(index, code, count)

    def direct_operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Execute a binary output command without prior SELECT."""
        return self._execute_binary_output(index, code, count)

    # -- Analog output helpers ------------------------------------------------

    def _validate_analog_output(self, index: int, value: float) -> CommandResult | None:
        """Return an error result if the AO index is missing or value out of range.

        NaN fails both range comparisons silently (every comparison against
        NaN is False), so it is checked explicitly and answered the same
        way the range check already answers: OUT_OF_RANGE, not a raise.
        """
        ao = self._ao_store.get(index)
        if ao is None:
            return CommandResult.not_supported(f"Analog output {index} not found")
        if math.isnan(value) or value < ao.minimum or value > ao.maximum:
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
