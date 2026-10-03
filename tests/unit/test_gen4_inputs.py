"""lua/gen4/inputs.lua -- the pack-only producers for the client's optional area / charmap / bag inputs.

Hermetic: the real module is loaded in lupa against a scratch pack tree (the REAL hgss
area_map.json / locations.json when a test wants them, otherwise a synthetic pack). No ROM, no
emulator, no .cache.

The contract under test is deliberately asymmetric: a producer must return the RIGHT value where
the pack carries the fact, and nil (never a guess) where it does not. Every "red control" mutates
one guard and asserts the named test's own assertion is what catches it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
INPUTS = (ROOT / "lua/gen4/inputs.lua").read_text(encoding="utf-8")
HGSS = ROOT / "data/games/gen4_hgss"
HGSS_MAP = json.loads((HGSS / "area_map.json").read_text(encoding="utf-8"))
HGSS_LOCS = json.loads((HGSS / "locations.json").read_text(encoding="utf-8"))


def lua_inputs(tmp: Path, src: str | None = None, *, areas: bool = False, locations: bool = True,
               charmap: dict | None = None, profile: str = "data/games/gen4_x/profile.json") -> dict:
    """Load inputs.lua in lupa over a scratch pack; returns the flat namespace it produced."""
    pack = tmp / "data/games/gen4_x"
    pack.mkdir(parents=True)
    (tmp / "lua").mkdir(exist_ok=True)
    (tmp / "lua/json_codec.lua").write_bytes((ROOT / "lua/json_codec.lua").read_bytes())
    (pack / "profile.json").write_text("{}", encoding="utf-8")
    if areas:
        (pack / "area_map.json").write_text(json.dumps(HGSS_MAP), encoding="utf-8")
    if locations:
        (pack / "locations.json").write_text(json.dumps(HGSS_LOCS), encoding="utf-8")
    if charmap is not None:
        (pack / "charmap.json").write_text(json.dumps(charmap), encoding="utf-8")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.ROOT_DIR, g.PROFILE = tmp.as_posix(), profile
    g.INPUTS_SRC = src if src is not None else INPUTS
    lua.execute("""
        local deps = { root = ROOT_DIR, json = assert(loadfile(ROOT_DIR .. "/lua/json_codec.lua"))(),
                       pack_profile = PROFILE }
        INPUTS = assert(load(INPUTS_SRC, "=inputs"))()
        area_of, AREA_WHY = INPUTS.area_of(deps)
        charmap, charmap_why = INPUTS.charmap(deps)
        bags, bags_why = INPUTS.has_pokeballs(deps)
        built, gaps = INPUTS.build(deps)
    """)

    # `raw` is what the producer returned (nil means it refused); `area` calls it and normalizes the
    # two return values to a list, so a refusal is `None` and never an empty pair.
    def call_area(map_id, loc=None):
        return list(g.area_of(map_id, loc if loc is not None else lua.table()))

    return {"lua": lua, "g": g, "raw": g.area_of, "area": call_area,
            "why": g.AREA_WHY, "charmap": g.charmap, "charmap_why": g.charmap_why,
            "bags": g.bags, "bags_why": g.bags_why, "built": g.built, "gaps": g.gaps}


def assert_area_contract(w):
    """The guard every area mutant must trip: a null/absent fact stays nil, a label is never invented."""
    assert w["area"](9) == ["route_1", "Route 1"]
    assert w["area"](0) == [None, "Mystery Zone"]     # JSON null -> nil area, label kept
    assert w["area"](9999) == [None, None]            # absent from both tables


# -- area_of: the one producer the pack can supply today -------------------------------------
def test_area_of_names_a_mapped_map_from_the_real_pack_files(tmp_path):
    w = lua_inputs(tmp_path, areas=True)
    assert w["raw"] is not None
    assert w["area"](9) == ["route_1", "Route 1"]     # MAP_ROUTE_1, per the generated pack
    # D10: the bug-catch contest is its own area inside National Park, and the game labels the map
    # "National Park" -- the pack's two tables answer two different questions.
    assert w["area"](487) == ["bug_catching_contest", "National Park"]
    assert w["area"](488) == ["national_park", "National Park"]


def test_an_unmapped_map_is_an_empty_area_not_a_guess_and_keeps_its_label(tmp_path):
    w = lua_inputs(tmp_path, areas=True)
    assert w["area"](0) == [None, "Mystery Zone"]     # JSON null in maps -> no Soul Link area
    assert w["area"](82)[0] is None                   # unused-only map section
    assert w["area"](9999) == [None, None]            # absent from both tables


def test_a_pack_with_no_area_map_refuses_the_area_input_by_name(tmp_path):
    w = lua_inputs(tmp_path, areas=False)
    assert w["raw"] is None
    assert "area_map.json" in str(w["why"])


def test_a_pack_with_no_locations_refuses_rather_than_returning_a_bare_area(tmp_path):
    w = lua_inputs(tmp_path, areas=True, locations=False)
    assert w["raw"] is None and "locations.json" in str(w["why"])


def test_a_bad_profile_path_refuses_before_touching_the_filesystem(tmp_path):
    w = lua_inputs(tmp_path, areas=True, profile="data/games/gen4_x/not_a_profile.json")
    assert w["raw"] is None and "pack_profile" in str(w["why"])


def test_an_area_producer_that_fills_a_missing_area_goes_red(tmp_path):
    """Mutant: unmapped maps get a fabricated id. The unmapped/null assertions must catch it."""
    mutant = INPUTS.replace("local area = maps[key]", "local area = maps[key] or 'route_1'")
    assert mutant != INPUTS
    assert_area_contract(lua_inputs(tmp_path / "real", areas=True))
    with pytest.raises(AssertionError):
        assert_area_contract(lua_inputs(tmp_path / "mut", areas=True, src=mutant))


def test_an_area_producer_that_invents_a_label_goes_red(tmp_path):
    """Mutant: a map with no name row gets one. The absent-map assertion must catch it."""
    mutant = INPUTS.replace('if type(name) ~= "string" then name = nil end',
                            'if type(name) ~= "string" then name = "Unknown" end')
    assert mutant != INPUTS
    assert_area_contract(lua_inputs(tmp_path / "real", areas=True))
    with pytest.raises(AssertionError):
        assert_area_contract(lua_inputs(tmp_path / "mut", areas=True, src=mutant))


def test_an_area_producer_that_swallows_a_json_null_goes_red(tmp_path):
    """Mutant: accept any table value as an area id, so a JSON null becomes the sentinel table."""
    mutant = INPUTS.replace('if type(area) ~= "string" then area = nil end', "")
    assert mutant != INPUTS
    assert_area_contract(lua_inputs(tmp_path / "real", areas=True))
    with pytest.raises(AssertionError):
        assert_area_contract(lua_inputs(tmp_path / "mut", areas=True, src=mutant))


# -- charmap: the pack does not ship one, so the producer must refuse ---------------------------
def test_charmap_is_nil_and_names_the_missing_pack_fact(tmp_path):
    w = lua_inputs(tmp_path)
    assert w["charmap"] is None
    why = str(w["charmap_why"])
    assert "charmap.json" in why and ".glyphs" in why, "the gap must name the file and the key"


def test_charmap_decodes_the_pack_codes_when_the_pack_ships_them(tmp_path):
    w = lua_inputs(tmp_path, charmap={"glyphs": {"289": "0", "299": "A"}, "terminator": 65535})
    assert w["charmap"] is not None
    assert w["charmap"][289] == "0" and w["charmap"][299] == "A"


def test_an_empty_or_garbled_charmap_file_refuses_instead_of_returning_an_empty_table(tmp_path):
    assert lua_inputs(tmp_path / "a", charmap={"glyphs": {}})["charmap"] is None
    w = lua_inputs(tmp_path / "b", charmap={"_note": "no glyphs key"})
    assert w["charmap"] is None and ".glyphs" in str(w["charmap_why"])


def test_a_charmap_producer_that_borrows_a_hardcoded_table_goes_red(tmp_path):
    """Mutant: a literal fallback table. The nil assertion must catch it."""
    mutant = INPUTS.replace('return nil, why .. " (" .. Inputs.GAPS.charmap .. ")"',
                            'return { [289] = "0" }')
    assert mutant != INPUTS
    assert lua_inputs(tmp_path, src=mutant)["charmap"] is not None, "the mutant guessed: this must go red"


# -- has_pokeballs: no pack fact at all ---------------------------------------------------------
def test_has_pokeballs_is_nil_and_names_the_missing_bag_fact(tmp_path):
    w = lua_inputs(tmp_path)
    assert w["bags"] is None
    why = str(w["bags_why"])
    for key in ("balls_pocket_off", "ball_slot_size", "ball_slot_count", "ball_ids"):
        assert key in why, f"the gap must name {key}"
    assert "save.array_ids.bag" in why, "the gap must point at the array id the pack DOES ship"


def test_a_ball_reader_that_returns_false_when_the_pack_is_silent_goes_red(tmp_path):
    """Mutant: `false` instead of nil. An absent producer must be distinguishable from an empty bag."""
    mutant = INPUTS.replace("    return nil, Inputs.GAPS.has_pokeballs", "    return false, Inputs.GAPS.has_pokeballs")
    assert mutant != INPUTS
    assert lua_inputs(tmp_path, src=mutant)["bags"] is not None, "the mutant answered: this must go red"


# -- build: what actually reaches the client ----------------------------------------------------
def test_build_omits_an_absent_producer_and_reports_every_gap(tmp_path):
    w = lua_inputs(tmp_path, areas=True, charmap={"glyphs": {"299": "A"}})
    built, gaps = w["built"], w["gaps"]
    assert built["area_of"] is not None and built["charmap"] is not None
    assert built["has_pokeballs"] is None and [g["name"] for g in gaps.values()] == ["has_pokeballs"]


def test_build_produces_no_key_at_all_when_every_producer_refuses(tmp_path):
    """A refused seam must be ABSENT from the client input: an empty table, so `p.has_pokeballs`
    reads as nil at the call site and the client's own optional guard holds."""
    w = lua_inputs(tmp_path, areas=False, charmap=None)
    assert list(w["built"].keys()) == []
    assert sorted(g["name"] for g in w["gaps"].values()) == ["area_of", "charmap", "has_pokeballs"]


def test_a_build_that_invents_every_seam_goes_red(tmp_path):
    """Mutant: build fills a refused seam with a no-op. The key-count assertion must catch it."""
    mutant = INPUTS.replace("        if value ~= nil then\n            out[name] = value",
                            "        if value ~= nil then\n            out[name] = value\n"
                            "        elseif name == 'has_pokeballs' then out[name] = function() return false end")
    assert mutant != INPUTS
    w = lua_inputs(tmp_path, src=mutant)
    # the real build (test above) has no has_pokeballs key; the mutant must visibly have one
    assert "has_pokeballs" in list(w["built"].keys()), "the mutant wired a fake: this must go red"


# -- the module itself --------------------------------------------------------------------------
def test_inputs_names_no_game_address_and_no_hex_literal():
    """Every fact is the pack's; a literal here would be a fact this file is forbidden to hold."""
    code = "\n".join(re.sub(r"--.*", "", ln) for ln in INPUTS.splitlines())
    assert re.findall(r"\b0[xX][0-9A-Fa-f]+\b", code) == []
    # word-boundary forms: a citation like "pokeheartgold@ad7a3afa" is allowed, a title branch is not
    for banned in ("heartgold", "soulsilver", "gen4_hg", "apricorn"):
        assert not re.search(rf"\b{banned}", code, re.IGNORECASE), f"{banned} must not name a title here"




@pytest.mark.parametrize("name", ["area_of", "charmap", "has_pokeballs"])
def test_every_producer_is_reachable_by_name_and_returns_a_value_or_a_reason(tmp_path, name):
    w = lua_inputs(tmp_path, areas=True, charmap={"glyphs": {"299": "A"}})
    produced = w["built"][name]
    gap_names = {g["name"] for g in w["gaps"].values()}
    assert (produced is not None) != (name in gap_names)
