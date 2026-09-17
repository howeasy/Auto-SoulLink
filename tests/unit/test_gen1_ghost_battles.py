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

P8-2b: the BEHAVIOUR is proved end-to-end against the rewritten client by
tests/unit/test_gen1_client.py::test_tower_ghost_battle_without_silph_scope_is_not_a_failed_encounter
(and the Scope control immediately after it), which drives a real battle rather than
grepping the source. What only this file can do is re-derive the two constants from the
decomps, so a map or item id that moves upstream fails here instead of silently widening or
narrowing the suppression.
"""
from __future__ import annotations

import os
import re

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CLIENT = os.path.join(_REPO, "lua", "gen1", "client.lua")


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
def client_src() -> str:
    with open(CLIENT, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def tower_maps(client_src) -> set[int]:
    """The map ids lua/gen1/client.lua actually suppresses on, parsed from its own table."""
    m = re.search(r"local TOWER_MAPS\s*=\s*\{(.*?)\}", client_src, re.S)
    assert m, "lua/gen1/client.lua no longer declares TOWER_MAPS"
    ids = {int(x, 16) for x in re.findall(r"\[0x([0-9A-Fa-f]+)\]\s*=\s*true", m.group(1))}
    assert ids, "TOWER_MAPS parsed empty — every assertion below would be vacuous"
    return ids


@pytest.fixture(scope="module")
def silph_scope(client_src) -> int:
    m = re.search(r"local SILPH_SCOPE\s*=\s*0x([0-9A-Fa-f]+)", client_src)
    assert m, "lua/gen1/client.lua no longer declares SILPH_SCOPE"
    return int(m.group(1), 16)


@pytest.mark.parametrize("decomp", ["pokered", "pokeyellow"])
def test_the_tower_map_ids_match_the_decomp(decomp, tower_maps):
    path = os.path.join(_find_pret(decomp), "constants", "map_constants.asm")
    if not os.path.exists(path):
        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    first = re.search(r"map_const POKEMON_TOWER_1F,.*?; \$([0-9A-F]{2})", src)
    last = re.search(r"map_const POKEMON_TOWER_7F,.*?; \$([0-9A-F]{2})", src)
    assert first and last, "the map constants moved"
    expected = set(range(int(first.group(1), 16), int(last.group(1), 16) + 1))
    assert tower_maps == expected, (
        f"{decomp}: the client suppresses no_catch on {sorted(tower_maps)}, but the Tower is "
        f"{sorted(expected)}. Too few leaves a floor dead-zoning on a ghost; too many stops a "
        f"real route from ever dead-zoning.")


@pytest.mark.parametrize("decomp", ["pokered", "pokeyellow"])
def test_the_silph_scope_id_matches_the_decomp(decomp, silph_scope):
    path = os.path.join(_find_pret(decomp), "constants", "item_constants.asm")
    if not os.path.exists(path):
        pytest.skip(f"{decomp} not cloned — run tools/build_pret_syms.py")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "const SILPH_SCOPE" in line:
                expected = int(re.search(r"\$([0-9A-Fa-f]{2})", line).group(1), 16)
                assert expected == silph_scope
                return
    pytest.fail("SILPH_SCOPE not found in the decomp")


def test_no_neighbouring_map_is_swept_up(tower_maps):
    """Boundaries: one below the Tower and one above must NOT be suppressed, or a real
    route silently stops dead-zoning."""
    assert min(tower_maps) - 1 not in tower_maps
    assert max(tower_maps) + 1 not in tower_maps
    assert len(tower_maps) == 7, f"the Tower has seven floors, got {sorted(tower_maps)}"
