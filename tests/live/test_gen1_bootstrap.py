import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

from server.gen1_bootstrap_receipt import validate
from server.gen1_initial_observation import display_name
from tools.run_gb_gate import BIZHAWK_CONFIG, run_gate
from tools.verify_canonical_sources import verify

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("SLINK_LIVE") != "1", reason="explicit live emulator lane required"
    ),
]


def run_bootstrap(variant, *, bounded=False):
    assert not verify()["failures"]
    fixture = ROOT / "tests/fixtures/gen1" / f"{variant}_town.SaveRAM"
    original_fixture = hashlib.sha256(fixture.read_bytes()).hexdigest()
    directory = Path(tempfile.mkdtemp(prefix="bootstrap-live-", dir=ROOT / ".cache"))
    output = directory / "result.json"
    blank = directory / "empty.SaveRAM"
    blank.write_bytes(b"\xff" * 0x8000)
    config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
    config["Rewind"]["Enabled"] = False
    private = directory / "config.ini"
    private.write_text(json.dumps(config))
    passed, path, log = run_gate(
        "lua/tests/test_gen1_bootstrap_gate.lua",
        rom_key=variant,
        quiet=True,
        timeout=240,
        config_base=str(private),
        fixture_override=str(blank),
        extra_env={
            "SLINK_BOOTSTRAP_RESULT": str(output),
            "SLINK_BOOTSTRAP_BOUNDED": "1" if bounded else "0",
        },
    )
    assert passed, f"{path}\n{log[-3000:]}"
    result = json.loads(output.read_text())
    assert result["passed"], result.get("error")
    assert result["restored"] and len(result["screenshots"]) >= 4
    assert all(Path(path).is_file() for path in result["screenshots"])
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == original_fixture
    row = result["result"]
    receipt = row["receipt"]
    point = receipt["end"]["point"]
    assert row["observer_equal"] and row["frames"] > 0
    assert row["normal_menu_entry"] and row["walked"]
    assert row["bounded"] is bounded
    if bounded:
        assert row["authorized_steps"] == row["frames"]
    for screenshot in result["screenshots"]:
        if ".observed-" in screenshot:
            assert (
                Path(screenshot).read_bytes()
                == Path(screenshot.replace(".observed-", ".baseline-")).read_bytes()
            )
    proof = validate(
        receipt,
        variant=variant,
        identity={
            "ot_id": point["player_id"],
            "trainer_name": display_name(bytes.fromhex(point["trainer"])),
        },
        context_generation="a" * 32,
        physical_instance="1" * 32,
        final_sha1=receipt["final_sha1"],
        source=row["point"],
        frame=row["frame"],
    )
    assert proof["entry_frame"] < proof["return_frame"] <= proof["frame"]


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_original_new_game_bootstrap_and_observer_differential(variant):
    run_bootstrap(variant)


@pytest.mark.parametrize("variant", ["red", "blue", "yellow"])
def test_source_observer_survives_bounded_normal_menu_bootstrap(variant):
    # The exact host actuator is real; its per-step authority is an explicit test
    # token, not server-backed permission for ordinary production gameplay.
    run_bootstrap(variant, bounded=True)
