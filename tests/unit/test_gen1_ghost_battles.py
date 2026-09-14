"""A battle the engine refuses to let you catch is not a failed encounter.

Pokémon Tower's ghosts cannot be caught until the player has the Silph Scope — not
"are hard to catch", but structurally cannot: `IsGhostBattle`
(pokered/engine/battle/core.asm:3309-3324) is

    wIsInBattle == 1  AND  POKEMON_TOWER_1F <= wCurMap <= POKEMON_TOWER_7F
    AND  the Silph Scope is not in the bag

and `ItemUseBall` (engine/items/item_effects.asm:149-153) then loads the "can't be caught"
value and jumps straight past the capture calculation.

`pokemon_tower` is a real encounter area — it has a Grass table in encounter_tables.json —
so the client saw an ordinary wild battle end with no capture, emitted `no_catch`, and
DEAD-ZONED POKEMON TOWER for both players. There is no route through the Tower that avoids
meeting a ghost, so this fired on every run, on both cartridges, for an encounter the game
never offered.

The constants are identical in pokered and pokeyellow, and this file re-derives them from
the decomps rather than trusting the Lua.
"""
from __future__ import annotations

import os
import re

import pytest

lupa = pytest.importorskip("lupa")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _find_pret(name: str) -> str:
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", name)


@pytest.fixture(scope="module")
def game():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    path = os.path.join(_REPO, "lua", "games", "gen1_rby.lua").replace("\\", "/")
    return lua.eval(f'dofile("{path}")')


# ── the constants, re-derived ────────────────────────────────────────────────────────

@pytest.mark.parametrize("decomp", ["pokered", "pokeyellow"])
def test_the_tower_map_ids_match_the_decomp(game, decomp):
    path = os.path.join(_find_pret(decomp), "constants", "map_constants.asm")
    if not os.path.exists(path):
        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    first = re.search(r"map_const POKEMON_TOWER_1F,.*?; \$([0-9A-F]{2})", src)
    last = re.search(r"map_const POKEMON_TOWER_7F,.*?; \$([0-9A-F]{2})", src)
    assert first and last, "the map constants moved"
    assert int(first.group(1), 16) == game.GHOST_MAP_FIRST
    assert int(last.group(1), 16) == game.GHOST_MAP_LAST


@pytest.mark.parametrize("decomp", ["pokered", "pokeyellow"])
def test_the_silph_scope_id_matches_the_decomp(game, decomp):
    path = os.path.join(_find_pret(decomp), "constants", "item_constants.asm")
    if not os.path.exists(path):
        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "const SILPH_SCOPE" in line:
                expected = int(re.search(r"\$([0-9A-Fa-f]{2})", line).group(1), 16)
                assert expected == game.ITEM_SILPH_SCOPE
                return
    pytest.fail("SILPH_SCOPE not found in the decomp")


# ── the predicate ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("map_id", [0x8E, 0x8F, 0x90, 0x91, 0x92, 0x93, 0x94])
def test_every_tower_floor_is_uncatchable_without_the_scope(game, map_id):
    assert game.is_uncatchable_battle(map_id, False) is True


@pytest.mark.parametrize("map_id", [0x8E, 0x91, 0x94])
def test_the_scope_makes_the_tower_catchable_again(game, map_id):
    """The control that stops this becoming 'the Tower never dead-zones'. After the Scope
    the ghosts are ordinary Gastly and Haunter and the area works like any other."""
    assert game.is_uncatchable_battle(map_id, True) is False


@pytest.mark.parametrize("map_id", [0x00, 0x0C, 0x8D, 0x95, 0xFF])
def test_no_other_map_is_affected(game, map_id):
    """Boundaries included: 0x8D is one below the Tower and 0x95 one above. An off-by-one
    here would silently stop a real route from ever dead-zoning."""
    assert game.is_uncatchable_battle(map_id, False) is False


def test_a_missing_map_id_is_not_uncatchable(game):
    """Reading the map can fail mid-transition; the safe default is to treat the battle
    as ordinary rather than to suppress a real dead zone."""
    assert game.is_uncatchable_battle(None, False) is False


# ── the client actually consults it ──────────────────────────────────────────────────

def test_the_client_suppresses_no_catch_for_these_battles():
    """Asserted on the source because the emit site is deep inside on_frame. The live
    proof is that the Tower still has its encounter table and the rule now leaves it
    alone; what this pins is that the guard is on the no_catch path at all."""
    path = os.path.join(_REPO, "lua", "clients", "gen1_rby_client.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"post_battle_frames == 1 and not captured_this_battle.*?no_catch",
                  src, re.S)
    assert m, "the no_catch emit site moved"
    assert "battle_uncatchable" in m.group(0), (
        "no_catch is emitted without consulting battle_uncatchable — Pokemon Tower will "
        "dead-zone on the first ghost")


def test_the_client_reads_the_flag_from_the_bag_and_the_map():
    path = os.path.join(_REPO, "lua", "clients", "gen1_rby_client.lua")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "G.is_uncatchable_battle(cur_map, M.hasBagItem(G.ITEM_SILPH_SCOPE))" in src, (
        "the flag must come from the live map and bag, not be assumed")
