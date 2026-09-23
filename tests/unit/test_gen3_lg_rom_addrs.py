"""C4-LGSE: LeafGreen's SE_SONG_HEADERS and evolution-CB2 ROM addresses must be LG's own,
not FireRed's. The Lua `vanilla` profile is one table shared by both titles (same bug class
the existing BASESTATS_ADDR override fixes), so the generator has to translate these by
symbol name out of pokeleafgreen.sym -- and refuse to build if a future value is left copied.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILE = REPO / "data" / "games" / "gen3_frlg" / "profile.json"
FR_SYM = REPO / "data/gen3/pret/pokefirered.sym"
LG_SYM = REPO / "data/gen3/pret/pokeleafgreen.sym"

# id -> the symbol name each SE_SONG_HEADERS slot names (see lua/games/gen3_frlge.lua's
# vanilla.SE_SONG_HEADERS comments).
SE_SYMBOLS = {
    16: "se_faint", 17: "se_flee", 22: "se_boo", 25: "se_success", 26: "se_failure",
    95: "se_shiny",
}
CB2_SYMBOLS = {
    "CB2_EVOLUTION_LOAD_ADDR": "CB2_EvolutionSceneLoadGraphics",
    "CB2_EVOLUTION_BEGIN_ADDR": "CB2_BeginEvolutionScene",
    "CB2_EVOLUTION_UPDATE_ADDR": "CB2_EvolutionSceneUpdate",
    "CB2_TRADE_EVOLUTION_UPDATE_ADDR": "CB2_TradeEvolutionSceneUpdate",
}

# FireRed's own literals, straight from lua/games/gen3_frlge.lua's vanilla table -- the
# regression guard for "the fix must never touch FireRed's values".
FR_SE_SONG_HEADERS = {
    16: 0x086B5984, 17: 0x086B59D4, 22: 0x086B5ADC, 25: 0x086B5BB0, 26: 0x086B5BE0,
    95: 0x086B6E70,
}
FR_CB2 = {
    "CB2_EVOLUTION_LOAD_ADDR": 0x080CE0E9, "CB2_EVOLUTION_BEGIN_ADDR": 0x080CDD19,
    "CB2_EVOLUTION_UPDATE_ADDR": 0x080CE711, "CB2_TRADE_EVOLUTION_UPDATE_ADDR": 0x080CE72D,
}


def _sym_addr(sym_path: pathlib.Path, name: str) -> int:
    """The one real (non `.gcc2_compiled.`) symbol address named `name` in a pret .sym file."""
    matches = re.findall(rf"^([0-9a-fA-F]{{8}})\s+[a-zA-Z]\s+[0-9a-fA-F]+\s+{re.escape(name)}$",
                         sym_path.read_text(encoding="utf-8"), re.M)
    assert len(matches) == 1, f"{sym_path.name}: {name} named {len(matches)} times"
    return int(matches[0], 16)


def _leafgreen() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))["titles"]["leafgreen"]


def _firered() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))["titles"]["firered"]


@pytest.mark.parametrize("song_id,symbol", sorted(SE_SYMBOLS.items()))
def test_leafgreen_se_song_header_matches_its_own_symbol(song_id, symbol):
    want = _sym_addr(LG_SYM, symbol)
    assert _leafgreen()["rom"]["SE_SONG_HEADERS"][str(song_id)] == want
    # never LG's address accidentally equal to FR's copied default
    assert want != FR_SE_SONG_HEADERS[song_id]


@pytest.mark.parametrize("key,symbol", sorted(CB2_SYMBOLS.items()))
def test_leafgreen_cb2_evolution_addr_matches_its_own_symbol(key, symbol):
    want = _sym_addr(LG_SYM, symbol) | 1  # Thumb: gMain.callback2 stores the +1 form
    assert _leafgreen()["rom"][key] == want
    assert want != FR_CB2[key]


def test_firered_se_song_headers_and_cb2_addrs_are_unchanged():
    fr = _firered()
    assert fr["rom"]["SE_SONG_HEADERS"] == {str(k): v for k, v in FR_SE_SONG_HEADERS.items()}
    for key, expected in FR_CB2.items():
        assert fr["rom"][key] == expected


def test_leafgreen_translation_has_a_src_citation():
    src = _leafgreen()["_src"]
    for song_id in SE_SYMBOLS:
        assert f"rom.SE_SONG_HEADERS.{song_id}" in src
        assert "pokeleafgreen.sym" in src[f"rom.SE_SONG_HEADERS.{song_id}"]
    for key in CB2_SYMBOLS:
        assert f"rom.{key}" in src
        assert "pokeleafgreen.sym" in src[f"rom.{key}"]


def test_guard_fires_on_a_synthetic_copied_value():
    """The general guard (not just the SE/CB2-specific fix): a leafgreen rom.* value left
    equal to FireRed's default, where FireRed's address names a real, globally-unique symbol
    that sits at a different address in pokeleafgreen.sym, must fail the build."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied, _sym_index

    fr_by_addr, fr_by_name = _sym_index(FR_SYM.read_text(encoding="utf-8"))
    _, lg_by_name = _sym_index(LG_SYM.read_text(encoding="utf-8"))
    # se_faint: FR's own address, never translated -- exactly this card's bug, reproduced
    # for a made-up key so the test doesn't depend on the real fix staying broken.
    bug_val = 0x086B5984
    fr_entry = {"ram": {}, "rom": {"SYNTHETIC_BUG": bug_val}, "derived": {}}
    lg_entry = {"ram": {}, "rom": {"SYNTHETIC_BUG": bug_val}, "derived": {}, "rom_thumb": []}
    with pytest.raises(SystemExit, match="rom.SYNTHETIC_BUG"):
        _guard_leafgreen_not_copied(lg_entry, fr_entry, fr_by_addr, fr_by_name, lg_by_name)


def test_guard_does_not_fire_on_a_genuinely_shared_address():
    """Task_LaunchLvlUpAnim (POST_BATTLE_WRITER_TASKS[0]) is a `static` helper repeated 3x in
    each .sym file -- not globally unique by name -- but the specific instance this task writer
    targets sits at the SAME address in both files (verified directly; see the
    _GUARD_EXCLUDE_PATHS comment in tools/gen_gen3_profile.py), so it is an explicit, documented
    exclusion and the guard must leave it alone."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied, _sym_index

    fr_by_addr, fr_by_name = _sym_index(FR_SYM.read_text(encoding="utf-8"))
    _, lg_by_name = _sym_index(LG_SYM.read_text(encoding="utf-8"))
    shared_val = 0x08030239  # Thumb form of 0x08030238, Task_LaunchLvlUpAnim in both .sym
    thumb = {"rom_thumb": ["POST_BATTLE_WRITER_TASKS"]}
    fr_entry = {"ram": {}, "rom": {"POST_BATTLE_WRITER_TASKS": [shared_val]}, "derived": {}}
    lg_entry = {"ram": {}, "rom": {"POST_BATTLE_WRITER_TASKS": [shared_val]}, "derived": {}, **thumb}
    _guard_leafgreen_not_copied(lg_entry, fr_entry, fr_by_addr, fr_by_name, lg_by_name)  # no raise


def test_guard_excludes_the_known_game_code_false_positive():
    """derived.BASESTATS_ADDR_BY_GAME_CODE.BPRE is keyed by FireRed's own game code, so its
    value is FR's gSpeciesInfo address by design -- the guard must not flag it even though
    FireRed's symbol at that address sits elsewhere in pokeleafgreen.sym."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied, _sym_index

    fr_by_addr, fr_by_name = _sym_index(FR_SYM.read_text(encoding="utf-8"))
    _, lg_by_name = _sym_index(LG_SYM.read_text(encoding="utf-8"))
    bpre_val = 0x08254784  # FireRed's own gSpeciesInfo address
    entry = {"ram": {}, "rom": {}, "rom_thumb": [],
             "derived": {"BASESTATS_ADDR_BY_GAME_CODE": {"BPRE": bpre_val, "BPGE": 0x08254760}}}
    _guard_leafgreen_not_copied(entry, entry, fr_by_addr, fr_by_name, lg_by_name)  # no raise


# ── Codex review of the first C4-LGSE cut: the guard resolved a symbol at an address without
# requiring it be unique GLOBALLY (only unique at that one address), and unconditionally
# stripped bit 0 before looking an address up. Each of the three falsifiers below reproduces
# a concrete bypass Codex found; each must be RED against the original, more permissive guard.

def test_guard_fails_closed_on_an_fr_address_that_names_two_aliases():
    """Bypass #1 (aliases): FR's old address names two symbols, Moved and Alias. LG moves
    Moved to a new address but keeps Alias at the old one. The old guard's `len(names) != 1:
    continue` silently accepted this (an ambiguous FR address was treated as "nothing to
    check"); the fix must fail closed instead."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied

    fr_by_addr = {0x08800000: ["Moved", "Alias"]}
    fr_by_name = {"Moved": [0x08800000], "Alias": [0x08800000]}
    lg_by_name = {"Alias": [0x08800000], "Moved": [0x08801000]}
    fr_entry = {"ram": {}, "rom": {"KEY": 0x08800000}, "derived": {}}
    lg_entry = {"ram": {}, "rom": {"KEY": 0x08800000}, "derived": {}, "rom_thumb": []}
    with pytest.raises(SystemExit, match="rom.KEY"):
        _guard_leafgreen_not_copied(lg_entry, fr_entry, fr_by_addr, fr_by_name, lg_by_name)


def test_guard_fails_closed_on_a_duplicate_lg_static():
    """Bypass #2 (duplicate statics): FR's old address uniquely names Static, but LG has a
    `static` of the same name at BOTH the old address and its relocated one. The old guard
    only checked "is the FR name present in LG's list AT the old address", which is true here
    even though the name is ambiguous in LG -- an address match at the old address proves
    nothing when the name recurs. The fix must require LG-global uniqueness too."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied

    fr_by_addr = {0x08800000: ["Static"]}
    fr_by_name = {"Static": [0x08800000]}
    lg_by_name = {"Static": [0x08800000, 0x08900000]}  # ambiguous: old address AND a new one
    fr_entry = {"ram": {}, "rom": {"KEY": 0x08800000}, "derived": {}}
    lg_entry = {"ram": {}, "rom": {"KEY": 0x08800000}, "derived": {}, "rom_thumb": []}
    with pytest.raises(SystemExit, match="rom.KEY"):
        _guard_leafgreen_not_copied(lg_entry, fr_entry, fr_by_addr, fr_by_name, lg_by_name)


def test_guard_catches_a_copied_odd_data_address():
    """Bypass #3 (odd data address): PP_UP_GET_MASK_ADDR is real DATA at an odd address
    (0x0825DEA1 in FireRed, gPPUpGetMask) -- not a Thumb pointer. The old guard unconditionally
    cleared bit 0 before looking the address up (0x0825DEA0 names nothing), missed the real
    symbol at the exact odd address, and let a copied value pass. The fix must look up the
    exact address first, and only strip the bit for keys actually marked Thumb (`rom_thumb`)."""
    from tools.gen_gen3_profile import _guard_leafgreen_not_copied, _sym_index

    fr_by_addr, fr_by_name = _sym_index(FR_SYM.read_text(encoding="utf-8"))
    _, lg_by_name = _sym_index(LG_SYM.read_text(encoding="utf-8"))
    bug_val = 0x0825DEA1  # FireRed's own gPPUpGetMask address, never translated
    fr_entry = {"ram": {}, "rom": {"PP_UP_GET_MASK_ADDR": bug_val}, "derived": {}}
    # correctly NOT marked Thumb -- it's data, exactly like the real profile
    lg_entry = {"ram": {}, "rom": {"PP_UP_GET_MASK_ADDR": bug_val}, "derived": {}, "rom_thumb": []}
    with pytest.raises(SystemExit, match="PP_UP_GET_MASK_ADDR"):
        _guard_leafgreen_not_copied(lg_entry, fr_entry, fr_by_addr, fr_by_name, lg_by_name)
