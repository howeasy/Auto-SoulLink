"""Real Gambatte memory, legacy deposit and original SaveGameData witnesses."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_memorial import expected
from tests.unit.test_gen1_memorial import fixture
from tools.run_gb_gate import run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"
    ),
]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_memorial_full_save_receipt_matches_real_cartridge_image(variant):
    assert not verify()["failures"]
    directory = Path(tempfile.mkdtemp(prefix="memorial-", dir=ROOT / ".cache"))
    cases = []
    for count, slot, initialized, pikachu in [
        (3, 1, True, False),
        (6, 5, False, False),
        (2, 0, True, variant == "yellow"),
    ]:
        before, key, identity = fixture(
            variant, count=count, slot=slot, initialized=initialized, pikachu=pikachu
        )
        cases.append({"before": before, "key": key, "identity": identity, "slot": slot})
    if variant == "yellow":
        for happiness in (0, 2, 3, 99, 100, 199, 200, 255):
            before, key, identity = fixture(
                variant, count=2, slot=0, pikachu=True, happiness=happiness
            )
            cases.append({"before": before, "key": key, "identity": identity, "slot": 0})
    input_path, output = directory / "input.json", directory / "result.json"
    input_path.write_text(json.dumps(cases))
    passed, path, log = run_gate(
        "lua/tests/test_gen1_memorial_receipt_gate.lua",
        rom_key=variant,
        quiet=True,
        extra_env={"SLINK_MEMORIAL_INPUT": str(input_path), "SLINK_MEMORIAL_RESULT": str(output)},
        timeout=100,
    )
    assert passed, f"{path}\n{log[-4000:]}"
    result = json.loads(output.read_text())
    assert result["passed"] and len(result["cases"]) == len(cases)
    for wanted, observed in zip(cases, result["cases"], strict=True):
        assert observed["before"] == wanted["before"]
        assert observed["after"] == expected(
            wanted["before"], wanted["key"], identity=wanted["identity"]
        )
