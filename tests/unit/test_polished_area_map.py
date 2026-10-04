"""Polished pack area_map.json (C-AREA): the key the client computes resolves to a real area.

lua/gen2/client.lua area_of() looks up area_map[tostring(group * 256 + number)] with (group, number) read from
wMapGroup/wMapNumber (lua/gen2/polished.lua read_map).  Derived here from the committed map_names.json, so no
pinned source checkout is needed; `tools/gen_polished_pack.py --check` covers source staleness.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_polished_pack as G  # noqa: E402

PACK = ROOT / "data/games/polished_crystal"
AREA = PACK / "area_map.json"


def _names():
    return json.loads((PACK / "map_names.json").read_text(encoding="utf-8"))


def _client_area(areas, group, number):
    """lua/gen2/client.lua area_of(), verbatim."""
    a = areas.get(str(group * 256 + number))
    return (a["area_id"], a["name"]) if a else ("", f"map_{group}_{number}")


def test_committed_file_is_the_deterministic_build_of_map_names():
    names = _names()
    first = G.json_bytes(G.build_area_map(names))
    assert first == G.json_bytes(G.build_area_map(copy.deepcopy(names)))
    raw = AREA.read_bytes()
    assert raw == first and b"\r" not in raw


def test_new_bark_town_resolves_through_the_client_key():
    names = _names()
    nb = next(m for m in names["maps"].values() if m["constant"] == "NEW_BARK_TOWN")
    areas = json.loads(AREA.read_text(encoding="utf-8"))
    assert _client_area(areas, nb["group"], nb["number"]) == ("new_bark_town", "New Bark Town")
    assert _client_area(areas, 0, 0)[0] == ""  # an unmapped pair still falls back, as before


def test_keys_unique_in_range_and_every_map_covered():
    areas = json.loads(AREA.read_text(encoding="utf-8"))
    names = _names()["maps"]
    assert len(areas) == len(names) == 605
    for k, a in areas.items():
        assert int(k) == a["map_group"] * 256 + a["map_number"]
        assert 1 <= a["map_group"] <= 37 and 1 <= a["map_number"] <= 255
        assert a["source"]["artifact"] == "polishedcrystal"
    assert {(a["map_group"], a["map_number"]) for a in areas.values()} == {(m["group"], m["number"]) for m in names.values()}
    assert areas[str(next(m["encoded_id"] for m in names.values() if m["constant"] == "NATIONAL_PARK_BUG_CONTEST"))]["area_id"] == "national_park_contest"


def test_red_control_a_mutated_key_breaks_new_bark_and_the_checker():
    areas = json.loads(AREA.read_text(encoding="utf-8"))
    nb = next(m for m in _names()["maps"].values() if m["constant"] == "NEW_BARK_TOWN")
    bad = dict(areas)
    bad[str(nb["group"] * 256 + nb["number"] + 1000)] = bad.pop(str(nb["group"] * 256 + nb["number"]))
    assert _client_area(bad, nb["group"], nb["number"])[0] == ""
    with pytest.raises(ValueError):
        G.check_area_map(bad)
    G.check_area_map(areas)
