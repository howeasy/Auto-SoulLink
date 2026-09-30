"""Pinned expansion gift/static declaration census; no live admission implied."""

import json
from pathlib import Path

from tools import gen_gen3_profile as profile


ROOT = profile.REPO
SOURCE = ROOT / ".cache/expansion-src"
OUTPUT = ROOT / "data/games/gen3_exp/28877d73/expansion_gifts.json"


def test_expansion_gift_census_preserves_active_and_excluded_sources():
    census = json.loads(OUTPUT.read_text(encoding="utf-8"))
    rows = census["declarations"]
    by_source = {(r["source"], r["line"]): r for r in rows}
    assert len(by_source) == len(rows)
    assert len(rows) == 61
    assert rows == sorted(rows, key=lambda r: (r["source"], r["line"]))
    assert any(r["kind"] == "gift" and r["species"] == "SPECIES_BELDUM"
               and r["status"] == "active" for r in rows)
    assert any(r["kind"] == "egg" and r["species"] == "SPECIES_WYNAUT"
               and r["status"] == "active" for r in rows)
    assert any(r["kind"] == "static" and r["species"] == "SPECIES_REGIROCK"
               and r["status"] == "active" for r in rows)
    assert any(r["source"].endswith("CeladonCity_GameCorner_PrizeRoom_Frlg/scripts.inc")
               and r["species"] == "VAR_TEMP_1" and r["status"] == "excluded"
               and "IS_FRLG" in r["condition"] for r in rows)
    assert any(r["source"] == "data/scripts/debug.inc" and r["status"] == "excluded"
               and r["species"] == "SPECIES_TREECKO" for r in rows)
    assert any(r["kind"] == "gift" and r["source"] == "src/battle_setup.c"
               and r["species"] == "starterMon" and r["status"] == "active" for r in rows)
    for r in rows:
        assert r["source"] and r["line"] > 0 and r["species"]
        source_line = (SOURCE / r["source"]).read_text(encoding="utf-8").splitlines()[r["line"] - 1]
        assert r["opcode"] in source_line and r["species"] in source_line
        if r["status"] == "active" and r["source"].startswith("data/maps/"):
            assert r["map_group_num"] is not None
            assert r["gift_area"] or r["unresolved_area"]


def test_expansion_gift_generator_parity_and_source_pin():
    from tools import gen_gen3_exp_gifts as gifts

    assert SOURCE.is_dir()
    assert gifts.build(SOURCE) == json.loads(OUTPUT.read_text(encoding="utf-8"))
