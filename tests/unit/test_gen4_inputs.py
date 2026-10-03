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
import struct
from pathlib import Path

import lupa
import pytest

from tests.unit.gen4_world import SD, World  # the model RAM + the PRODUCTION client

ROOT = Path(__file__).resolve().parents[2]
INPUTS = (ROOT / "lua/gen4/inputs.lua").read_text(encoding="utf-8")
HGSS = ROOT / "data/games/gen4_hgss"
HGSS_MAP = json.loads((HGSS / "area_map.json").read_text(encoding="utf-8"))
HGSS_LOCS = json.loads((HGSS / "locations.json").read_text(encoding="utf-8"))


TITLE = "testtitle"

# A synthetic profile.bag. Every field is the one the generated packs carry, at values small enough
# to read by eye; the tests below lay the fake array out at THESE offsets, so a producer that walks
# the pocket with its own arithmetic lands on bytes nobody wrote and answers nil.
BAG = {
    "array_id": 3, "base": "bag_array", "balls_pocket_off": 16,
    "ball_slot_size": 4, "ball_slot_count": 4,
    "slot_fields": {"id": {"off": 0, "size": 2}, "quantity": {"off": 2, "size": 2}},
    "ball_ids": [4, 5, 6], "note": "synthetic",
}


# None is a REAL bag value here (it emits the pack's JSON null), so the "use the synthetic fact"
# default is a sentinel rather than None.
_BAG_DEFAULT = object()


def pack_titles(bag=_BAG_DEFAULT, open_bag: str | None = None) -> dict:
    """profile.json `titles` with one title, its bag fact (bag=None emits the JSON null) and open."""
    title: dict = {"profile": {"bag": BAG if bag is _BAG_DEFAULT else bag}}
    if open_bag is not None:
        title["open"] = {"bag": open_bag}
    return {TITLE: title}


def bag_memory(slots: list[tuple[int, int]]) -> dict[int, int]:
    """u16 memory of the balls pocket: `slots` padded with empty slots up to ball_slot_count.

    Written at the PACK's offsets (never the producer's), so an answer other than the one these
    bytes describe is the producer's error, not the fixture's."""
    filled = list(slots) + [(0, 0)] * (BAG["ball_slot_count"] - len(slots))
    mem = {}
    for i, (item_id, qty) in enumerate(filled[:BAG["ball_slot_count"]]):
        base = BAG["balls_pocket_off"] + i * BAG["ball_slot_size"]
        mem[base + BAG["slot_fields"]["id"]["off"]] = item_id
        mem[base + BAG["slot_fields"]["quantity"]["off"]] = qty
    return mem


def lua_inputs(tmp: Path, src: str | None = None, *, areas: bool = False, locations: bool = True,
               charmap: dict | None = None, titles: dict | None = None, bag_mem: dict | None = None,
               array_refuses: bool = False, save_array: bool = True,
               profile: str = "data/games/gen4_x/profile.json") -> dict:
    """Load inputs.lua in lupa over a scratch pack; returns the flat namespace it produced.

    `titles` writes profile.json's title table (the bag fact's home). `bag_mem` is the fake save
    array: save_array(array_id) hands back a reader over it, `array_refuses` models an unreadable
    save (R.save_data's refusal), which must never read as an empty bag, and `save_array=False`
    withholds the handle entirely, which is what an unwired composition root looks like."""
    pack = tmp / "data/games/gen4_x"
    pack.mkdir(parents=True)
    (tmp / "lua").mkdir(exist_ok=True)
    (tmp / "lua/json_codec.lua").write_bytes((ROOT / "lua/json_codec.lua").read_bytes())
    (pack / "profile.json").write_text(json.dumps({"titles": titles} if titles else {}), encoding="utf-8")
    if areas:
        (pack / "area_map.json").write_text(json.dumps(HGSS_MAP), encoding="utf-8")
    if locations:
        (pack / "locations.json").write_text(json.dumps(HGSS_LOCS), encoding="utf-8")
    if charmap is not None:
        (pack / "charmap.json").write_text(json.dumps(charmap), encoding="utf-8")

    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.ROOT_DIR, g.PROFILE, g.TITLE = tmp.as_posix(), profile, TITLE
    g.INPUTS_SRC = src if src is not None else INPUTS
    g.BAG_ARRAY = BAG["array_id"]
    g.BAG_MEM = lua.table_from(bag_mem or {})
    g.ARRAY_REFUSES, g.HAS_SAVE_ARRAY = array_refuses, save_array
    lua.execute("""
        local deps = { root = ROOT_DIR, json = assert(loadfile(ROOT_DIR .. "/lua/json_codec.lua"))(),
                       pack_profile = PROFILE, title = TITLE }
        -- The seam run.lua owns: resolve the array by id, then read ARRAY-relative offsets from it.
        if HAS_SAVE_ARRAY then
            deps.save_array = function(array_id)
                if ARRAY_REFUSES then return nil, "null_ptr" end
                if array_id ~= BAG_ARRAY then return nil, "bad_array_id" end
                return function(off, len) return BAG_MEM[off] end
            end
        end
        INPUTS = assert(load(INPUTS_SRC, "=inputs"))()
        area_of, AREA_WHY = INPUTS.area_of(deps)
        charmap, charmap_why = INPUTS.charmap(deps)
        bags, bags_why = INPUTS.has_pokeballs(deps)
        -- called directly, once: a refusal is (nil, reason), an answer is true/false, and the
        -- globals are always strings/booleans so a Lua nil reads as Python None, never as AttributeError
        ball_v, ball_w = nil, tostring(bags_why)
        if bags then
            local v, why = bags()
            ball_v, ball_w = v, tostring(why or "")
        end
        built, gaps = INPUTS.build(deps)
    """)

    # `raw` is what the producer returned (nil means it refused); `area` calls it and normalizes the
    # two return values to a list, so a refusal is `None` and never an empty pair.
    def call_area(map_id, loc=None):
        return list(g.area_of(map_id, loc if loc is not None else lua.table()))

    return {"lua": lua, "g": g, "raw": g.area_of, "area": call_area,
            "why": g.AREA_WHY, "charmap": g.charmap, "charmap_why": g.charmap_why,
            "bags": g.bags, "bags_why": g.bags_why,
            "ball": g.ball_v, "ball_why": g.ball_w,
            "built": g.built, "gaps": g.gaps}


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


# -- charmap: the pack's own glyph table ----------------------------------------------------------
def test_charmap_is_nil_and_names_the_missing_pack_file(tmp_path):
    w = lua_inputs(tmp_path)
    assert w["charmap"] is None
    why = str(w["charmap_why"])
    assert "charmap.json" in why, "the gap must name the file the pack would carry it in"


def test_charmap_round_trips_the_pack_codes_under_number_keys(tmp_path):
    """client.lua hands R.decode_name the u16s straight from RAM, so a string key would miss every
    lookup: the decimal-string keys the file ships must come back as numbers."""
    w = lua_inputs(tmp_path, charmap={"glyphs": {"0": " ", "289": "0", "299": "A", "65534": "Z"},
                                      "terminator": 65535})
    assert w["charmap"] is not None
    assert w["charmap"][0] == " " and w["charmap"][289] == "0"
    assert w["charmap"][299] == "A" and w["charmap"][65534] == "Z"
    # R.decode_name indexes with a number, so a string-keyed table would decode to every "<$XXXX>"
    lua_vals = list(w["g"].charmap.values())
    assert len(lua_vals) == 4, "one entry per shipped glyph, no duplicates from the conversion"


def test_an_empty_or_garbled_charmap_file_refuses_instead_of_returning_an_empty_table(tmp_path):
    assert lua_inputs(tmp_path / "a", charmap={"glyphs": {}})["charmap"] is None
    w = lua_inputs(tmp_path / "b", charmap={"_note": "no glyphs key"})
    assert w["charmap"] is None and ".glyphs" in str(w["charmap_why"])


def test_a_charmap_producer_that_borrows_a_hardcoded_table_goes_red(tmp_path):
    """Mutant: a literal fallback table where the pack has none. The nil assertion must catch it."""
    mutant = INPUTS.replace(
        '    doc, why = load_optional(deps.json, deps.root .. "/" .. dir .. "charmap.json")\n'
        '    if not doc then return nil, why end',
        '    doc, why = nil, nil\n    if not doc then return { [289] = "0" } end')
    assert mutant != INPUTS
    assert lua_inputs(tmp_path, src=mutant)["charmap"] is not None, "the mutant guessed: this must go red"


# -- has_pokeballs: the pack's bag pocket, read through run.lua's save seam ----------------------
def assert_bag_contract(w, expected):
    """The guard every bag mutant must trip: a held ball, an empty pocket and an unreadable save are
    three DIFFERENT answers."""
    assert w["ball"] is expected, f"expected {expected}, got {w['ball']} ({w['ball_why']})"


def test_a_held_ball_in_the_pack_pocket_reads_true(tmp_path):
    w = lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(4, 5)]))
    assert w["bags"] is not None
    assert_bag_contract(w, True)


def test_a_ball_further_along_the_pocket_reads_true(tmp_path):
    """slot 2, so the pocket offset and stride must both be walked, not just the first slot."""
    assert_bag_contract(lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(0, 0), (0, 0), (5, 1)])), True)


def test_an_empty_ball_pocket_reads_false(tmp_path):
    assert_bag_contract(lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([])), False)


def test_a_stocked_item_the_pack_does_not_call_a_ball_reads_false(tmp_path):
    """id 7 carries a quantity but is not in ball_ids: a stocked bag is not a ball pocket."""
    assert_bag_contract(lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(7, 5)])), False)


def test_a_ball_id_at_quantity_zero_reads_false(tmp_path):
    assert_bag_contract(lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(4, 0), (6, 0)])), False)


def test_an_unreadable_save_is_unknown_and_never_false(tmp_path):
    """R.save_data's refusal must stay UNKNOWN: the client's seam answers `... or false`, so a false
    here would assert an empty pocket the save never reported."""
    w = lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(4, 5)]), array_refuses=True)
    assert w["bags"] is not None, "the producer exists; only the read is refused"
    assert_bag_contract(w, None)
    assert "null_ptr" in str(w["ball_why"]), "the refusal must reach the caller by name"


def test_a_slot_nobody_wrote_reads_unknown_rather_than_empty(tmp_path):
    """a pocket the fixture did not fill: an unreadable slot is not an empty slot."""
    w = lua_inputs(tmp_path, titles=pack_titles(), bag_mem={})
    assert_bag_contract(w, None)


def test_a_null_bag_is_a_named_gap_quoting_the_packs_own_reason(tmp_path):
    w = lua_inputs(tmp_path, titles=pack_titles(bag=None, open_bag="no pinned source clone for the bag"))
    assert w["bags"] is None
    why = str(w["bags_why"])
    assert "profile.bag" in why and "open.bag" in why, "the gap must name the key and where reasons live"
    assert "no pinned source clone for the bag" in why, "the reason is the pack's, quoted verbatim"


def test_a_bag_key_with_no_reason_still_names_where_one_would_be(tmp_path):
    w = lua_inputs(tmp_path, titles=pack_titles(bag=None))
    assert w["bags"] is None and "open.bag" in str(w["bags_why"])


def test_a_composition_root_without_the_save_seam_refuses_the_bag_by_name(tmp_path):
    w = lua_inputs(tmp_path, titles=pack_titles(), bag_mem=bag_memory([(4, 5)]), save_array=False)
    assert w["bags"] is None and "save_array" in str(w["bags_why"])


def test_a_ball_reader_that_answers_false_for_an_unreadable_save_goes_red(tmp_path):
    """Mutant: `return false` where the read refused. The unknown assertions must catch it."""
    mutant = INPUTS.replace(
        '        if not at then return nil, "bag array " .. tostring(bag.array_id) .. ": " .. tostring(rwhy) end',
        '        if not at then return false end')
    assert mutant != INPUTS
    with pytest.raises(AssertionError):
        assert_bag_contract(lua_inputs(tmp_path / "mut", titles=pack_titles(),
                                       bag_mem=bag_memory([(4, 5)]), array_refuses=True, src=mutant), None)


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


# -- client:save_array: the reader run.lua composes for the producers ---------------------------
# The bag producer names no address: it asks for an array id and reads ARRAY-relative offsets. The
# only place that can answer is the client itself (client.lua session.save_array, over the same
# R.save_data -> R.array every other read uses), so these drive the PRODUCTION client over the model
# RAM. BAG["array_id"] is the bag array every Gen 4 pack declares (profile.save.array_ids.bag).
BAG_SIZE, BAG_OFF = 0x200, 0x2000


def lay_out_bag(w, *, size=BAG_SIZE, off=BAG_OFF):
    """Write the bag array header into the model save and return (base address, size)."""
    sv = w.prof["save"]
    w.put(SD + sv["array_headers_off"] + BAG["array_id"] * sv["array_header_size"],
          struct.pack("<IIIHH", BAG["array_id"], size, off, 0, 0))
    return w.dyn + off, size


def reader(w):
    return w.session.save_array(w.session, BAG["array_id"])


def test_client_save_array_reads_the_pack_ball_pocket_out_of_the_model_ram():
    """Every offset in profile.bag is ARRAY-relative, so the bytes the pocket names are the bytes
    the reader returns -- read through the client's own save/array resolution."""
    w = World()
    base, _ = lay_out_bag(w)
    slot = BAG["balls_pocket_off"]
    idf, qtf = BAG["slot_fields"]["id"], BAG["slot_fields"]["quantity"]
    for i in range(BAG["ball_slot_count"]):
        item_id, qty = (4, 5) if i == 0 else (0, 0)
        at = slot + i * BAG["ball_slot_size"]
        w.w(base + at + idf["off"], item_id, idf["size"])
        w.w(base + at + qtf["off"], qty, qtf["size"])
    read = reader(w)
    for i in range(BAG["ball_slot_count"]):
        at = slot + i * BAG["ball_slot_size"]
        assert read(at + idf["off"], idf["size"]) == (4 if i == 0 else 0)
        assert read(at + qtf["off"], qtf["size"]) == (5 if i == 0 else 0)
    # a u32 read crosses the slot boundary and still lands inside the array
    assert read(slot, 4) == (4 | 5 << 16)


def test_client_save_array_offsets_are_relative_to_the_array_base():
    """A distinct word before the array base and a distinct word at it: the reader starts at base."""
    w = World()
    base, _ = lay_out_bag(w)
    w.w(base - 2, 0xBEEF, 2)
    w.w(base + 0, 0xCAFE, 2)
    read = reader(w)
    assert read(0, 2) == 0xCAFE
    value, why = read(-2, 2)     # the reader refuses below the base, it does not wrap into the block
    assert value is None and "out_of_array" in why


def test_client_save_array_refuses_a_read_past_the_end_of_the_array():
    w = World()
    _, size = lay_out_bag(w)
    read = reader(w)
    assert read(size - 2, 2) == 0                       # the last bytes are readable
    for off, length in ((size - 2, 4), (size, 2), (-2, 2), (0, 0), (1.5, 2)):
        value, why = read(off, length)
        assert value is None and "out_of_array" in why, f"offset {off}/{length} must refuse by name"


def test_client_save_array_refuses_an_array_the_save_does_not_map():
    """Three refusals, each by name: an array the header table leaves unmapped, an id the table does
    not carry at all, and a save block that is not there (a null pointer cell)."""
    w = World()
    lay_out_bag(w)
    value, why = w.session.save_array(w.session, 6)         # a header no one wrote: size 0
    assert value is None and "bad_array" in why
    value, why = w.session.save_array(w.session, w.prof["save"]["array_header_count"])
    assert value is None and "bad_array_id" in why
    w.w(w.prof["save_ptr"]["address"], 0)
    value, why = reader(w)
    assert value is None and why == "null_ptr"


def test_client_save_array_resolves_the_save_block_again_on_every_call():
    """No cached base: the game rewrites its save, and a re-created block is a different address.
    A reader handed out BEFORE the move still reads the block it was resolved over (the resolution
    happens in save_array, once), while a reader resolved after it reads the new one."""
    w = World()
    base, _ = lay_out_bag(w)
    w.w(base + 4, 0x1111, 2)
    before = reader(w)
    assert before(4, 2) == 0x1111
    moved = SD + 0x20000
    w.put(moved, w.get(SD, 0x30000))                   # the same block, re-created somewhere else
    w.w(moved + (base - SD) + 4, 0x2222, 2)
    w.w(w.prof["save_ptr"]["address"], moved)
    assert before(4, 2) == 0x1111, "a handed-out reader must keep its own array"
    assert reader(w)(4, 2) == 0x2222, "save_array cached the SaveData base across calls"
