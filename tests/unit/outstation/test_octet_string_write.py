"""#82: a WRITE of g110 or g111 used to be refused at framing (IIN2.1,
unknown width, never reaching Outstation._handle_write). It now frames and
is refused by the write path instead: ``_write_block_error`` has no entry
for either group, so it still answers IIN2.1, but through
``_write_block_check`` this time. Same answer, a different path: this pins
that the dispatch now happens, and that the answer bytes stay the same.
"""

import pytest

from dnp3.outstation import outstation as outstation_module
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import Outstation

# IIN1 with only DEVICE_RESTART set (time_sync_required=False below keeps
# NEED_TIME out of it, per tests/unit/outstation/test_request_framing.py).
_IIN1_RESTART = 0x80
_IIN2_OBJECT_UNKNOWN = 0x02


def _null_response(seq: int) -> bytes:
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, _IIN2_OBJECT_UNKNOWN])


class TestOctetStringWriteReachesTheWriteCheck:
    """The request now completes framing and reaches _write_block_check,
    where before it was refused at framing and never dispatched.
    """

    def test_g110v2_write_reaches_write_block_check_and_answers_object_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checked: list[tuple[int, int]] = []
        original = outstation_module._write_block_error

        def spy(block: object) -> object:
            checked.append((block.header.group, block.header.variation))  # type: ignore[attr-defined]
            return original(block)  # type: ignore[arg-type]

        monkeypatch.setattr(outstation_module, "_write_block_error", spy)
        outstation = Outstation(config=OutstationConfig(time_sync_required=False))
        # g110v2 (A.41.1): qualifier 0x17, count 1, index 0, 2-octet payload.
        request = bytes([0xC5, 0x02, 110, 2, 0x17, 1, 0, 0xAA, 0xBB])

        responses = outstation.process_request(request)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _null_response(5)
        assert checked == [(110, 2)]
