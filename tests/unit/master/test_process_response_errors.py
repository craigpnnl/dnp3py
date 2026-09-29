"""``Master.process_response`` catches only the parser's ``ParseError``.

Regression cover for issue #66: a bare ``except Exception`` flattened every
parse failure to ``None`` with nothing logged, and would have swallowed a
programming error inside the parser the same way it swallows a malformed
fragment from the outstation.
"""

import logging

import pytest

from dnp3.application.parser import parse_response
from dnp3.master import master as master_module
from dnp3.master.master import Master

# A well-formed RESPONSE header: FIR+FIN, seq 1, function RESPONSE, IIN 0.
WELL_FORMED_RESPONSE = bytes([0xC1, 0x81, 0x00, 0x00])


class TestMalformedResponseReturnsNoneAndLogs:
    """A malformed fragment is reported, not silently dropped."""

    def test_empty_payload_returns_none(self) -> None:
        master = Master()

        assert master.process_response(b"") is None

    def test_empty_payload_logs_a_warning_naming_the_parse_error(self, caplog: pytest.LogCaptureFixture) -> None:
        master = Master()

        with caplog.at_level(logging.WARNING, logger="dnp3.master.master"):
            master.process_response(b"")

        warnings = [r for r in caplog.records if r.name == "dnp3.master.master" and r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "Response header requires" in warnings[0].getMessage()

    def test_truncated_payload_returns_none_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        master = Master()

        with caplog.at_level(logging.WARNING, logger="dnp3.master.master"):
            result = master.process_response(bytes([0xC1]))

        assert result is None
        warnings = [r for r in caplog.records if r.name == "dnp3.master.master" and r.levelname == "WARNING"]
        assert len(warnings) == 1


class TestWellFormedResponseIsUnchanged:
    """The narrowed handler does not touch the success path."""

    def test_well_formed_response_still_returns_response_info(self) -> None:
        master = Master()

        info = master.process_response(WELL_FORMED_RESPONSE)

        assert info is not None
        assert info.function.value == 0x81
        assert info.sequence == 1
        assert info.fir is True
        assert info.fin is True

    def test_well_formed_response_matches_direct_parse(self) -> None:
        """Sanity check: process_response's success path still agrees with parse_response."""
        master = Master()
        fragment = parse_response(WELL_FORMED_RESPONSE)

        info = master.process_response(WELL_FORMED_RESPONSE)

        assert info is not None
        assert info.sequence == fragment.header.control.seq


class TestNonParseErrorPropagates:
    """Anything the parser did not itself signal as a parse failure escapes."""

    def test_injected_runtime_error_is_not_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(data: bytes) -> object:
            msg = "not a parse failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(master_module, "parse_response", _boom)
        master = Master()

        with pytest.raises(RuntimeError, match="not a parse failure"):
            master.process_response(WELL_FORMED_RESPONSE)

    def test_injected_type_error_is_not_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(data: bytes) -> object:
            raise TypeError("wrong shape")

        monkeypatch.setattr(master_module, "parse_response", _boom)
        master = Master()

        with pytest.raises(TypeError, match="wrong shape"):
            master.process_response(WELL_FORMED_RESPONSE)
