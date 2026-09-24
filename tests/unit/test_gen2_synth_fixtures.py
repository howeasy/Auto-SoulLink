"""O-33 synthetic setup builder (tools/gen2_synth_fixtures.py): valid copies/checksums, the decoded party is the spec,
and the disclosure names every changed byte (the checksums aside)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from server.adapters import gen2_codec as codec  # noqa: E402
from tools import gen2_synth_fixtures as synth  # noqa: E402

EDITS = {"party": [{"species": "CATERPIE", "level": 6, "exp": 342, "moves": ["TACKLE", "STRING_SHOT"]},
                   {"species": "SENTRET", "egg": True, "happiness": 1, "moves": ["TACKLE"]},
                   {"species": "PIDGEY", "level": 5, "moves": ["TACKLE"], "hp": 1, "status": synth.PSN}],
         "balls": [["MASTER_BALL", 5]], "step_count": 0x7F, "poison_step": 3, "last_spawn": "VIOLET_CITY"}


def base(title):
    path = ROOT / "tests/fixtures/gen2" / f"{title}_battle.SaveRAM"
    if not path.exists():
        pytest.skip(f"{path.name} missing")
    return path.read_bytes()


@pytest.mark.parametrize("title", ["crystal", "gold"])
def test_the_built_save_is_valid_and_carries_the_spec(title):
    raw = base(title)
    out, disclosure = synth.build(title, raw, EDITS, base_name=f"{title}_battle")
    layout = codec.for_foundation(title)
    assert codec.strict_checksum_witness(out[:synth.CART], layout)["valid"]
    assert out[synth.CART:] == raw[synth.CART:]   # the RTC trailer is untouched
    for copy_name in ("primary", "backup"):
        party = codec.decode_saved_party(out[:synth.CART], layout, copy_name=copy_name)
        rows = [(m["species_id"], m["is_egg"], m["level"], m["exp"], m["hp"], m["status"], m["happiness"])
                for m in party["mons"]]
        assert rows == [(10, False, 6, 342, 23, 0, 70), (161, True, 5, 125, 20, 0, 1), (16, False, 5, 135, 1, 8, 70)]
    assert disclosure["base_sha256"] != disclosure["sha256"] and disclosure["edits"] == EDITS


def test_the_disclosure_names_every_changed_byte():
    raw = base("crystal")
    out, disclosure = synth.build("crystal", raw, EDITS)
    layout = codec.for_foundation("crystal")
    covered = set()
    for field in disclosure["fields"]:
        for at in (field["primary"], field["backup"]):
            covered |= set(range(at, at + field["size"]))
            assert out[at:at + field["size"]].hex() == field["new_hex"]
            assert raw[at:at + field["size"]].hex() == field["old_hex"]
    for at in layout.checksum_offsets.values():
        covered |= {at, at + 1}
    changed = {i for i in range(synth.CART) if raw[i] != out[i]}
    assert changed and changed <= covered
    assert {f["symbol"] for f in disclosure["fields"]} >= {"wPartyCount", "wPartyMon1", "wBalls",
                                                           "wLastSpawnMapGroup", "wStepCount", "wPoisonStepCount"}


@pytest.mark.parametrize("edits, match", [
    ({"party": [{"species": "CATERPIE", "level": 7, "exp": 342, "moves": ["TACKLE"]}]}, "not level"),
    ({"last_spawn": "ROUTE_29"}, "not a spawn point"),
    ({"party": [{"species": "CATERPIE", "level": 6, "moves": []}]}, "moves required"),
])
def test_contradictory_edits_are_refused(edits, match):
    with pytest.raises(ValueError, match=match):
        synth.build("crystal", base("crystal"), edits)
