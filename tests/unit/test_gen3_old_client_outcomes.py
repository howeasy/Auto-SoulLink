"""The shipped old Gen 3 client's battle-outcome defaults must be pret's B_OUTCOME_* values.

Until 2026-09-23 lua/memory_gba.lua defaulted vanilla FRLG to CAUGHT=6/RAN=3 (B_OUTCOME_MON_FLED /
B_OUTCOME_DREW), so every vanilla catch was misjudged. The reference is the new gen3_frlg pack,
whose values are generated from pret (tools/gen_gen3_profile.py).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pack_outcomes():
    titles = json.loads((ROOT / "data/games/gen3_frlg/profile.json").read_text(encoding="utf-8"))["titles"]
    return {t: (v["derived"]["OUTCOME_CAUGHT"], v["derived"]["OUTCOME_RAN"]) for t, v in titles.items()
            if t in ("firered", "leafgreen")}


def test_old_client_defaults_match_the_pret_derived_pack():
    src = (ROOT / "lua/memory_gba.lua").read_text(encoding="utf-8")
    caught = {int(v) for v in re.findall(r"M\.OUTCOME_CAUGHT\s*=\s*(\d+)", src)}
    ran = {int(v) for v in re.findall(r"M\.OUTCOME_RAN\s*=\s*(\d+)", src)}
    for title, (pack_caught, pack_ran) in _pack_outcomes().items():
        assert caught == {pack_caught}, (title, caught)
        assert ran == {pack_ran}, (title, ran)


def test_no_vanilla_profile_overrides_the_defaults_back():
    src = (ROOT / "lua/games/gen3_frlge.lua").read_text(encoding="utf-8")
    assert not re.search(r"OUTCOME_CAUGHT\s*=\s*6|OUTCOME_RAN\s*=\s*3\b", src)
