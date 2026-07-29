"""Every rom_type a game module can emit must resolve to an adapter.

WHY THIS EXISTS. `lua/games/gen2_crystal.lua:rom_type_for_variant` returns "Gold", "Silver"
and "Crystal (AP)". None were registered in `_ROM_TYPE_TO_GAME_ID`, so
`game_id_for_rom_type()` returned None, the guard in `server/server.py` never switched the
adapter, and a Gold run continued under whichever adapter was already loaded — the Gen 3
default. Nothing raised, nothing warned, and the wrong `game_id` was then persisted into the
run directory, so the mistake outlived the session that made it.

That is the worst shape a bug can take here: it makes every later measurement lie. A Gold
run would report Gen 3 species names and Gen 3 gift areas, and look like a Gen 2 data
problem rather than a routing one.

The test drives the REAL Lua under lupa rather than restating a list of strings in Python.
A hand-maintained list would have been just as wrong as the dict it was checking — both
would have been written from the same mistaken belief about what the module returns.
"""
import glob
import os
import re

import pytest

lupa = pytest.importorskip("lupa")

from server.adapters import _ROM_TYPE_TO_GAME_ID, _VARIANT_LABEL  # noqa: E402
from server.adapters import game_id_for_rom_type, variant_label  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Game modules that expose rom_type_for_variant + a PROFILES table. Gen 4/5 are NDS and
# resolve their rom_type differently, so they are covered by their own adapter tests.
GB_GBA_MODULES = [
    ("lua/games/gen1_rby.lua", "gen1_rby"),
    ("lua/games/gen2_crystal.lua", "gen2_crystal"),
]


def _load(rel_path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("print = function() end")
    return lua.eval(f'dofile("{os.path.join(REPO, rel_path).replace(chr(92), "/")}")')


def _variants(mod):
    """Every key in M.PROFILES, including metatable-inherited aliases."""
    return sorted(dict(mod.PROFILES).keys())


@pytest.mark.parametrize("rel_path,expected_game_id", GB_GBA_MODULES,
                         ids=lambda v: v if isinstance(v, str) else str(v))
def test_every_variant_routes_to_its_adapter(rel_path, expected_game_id):
    """The load-bearing assertion: no variant may fall through to the default adapter."""
    mod = _load(rel_path)
    unrouted = []
    for variant in _variants(mod):
        rom_type = mod.rom_type_for_variant(variant)
        if game_id_for_rom_type(rom_type) != expected_game_id:
            unrouted.append(
                f"  variant {variant!r} -> rom_type {rom_type!r} -> "
                f"{game_id_for_rom_type(rom_type)!r}, expected {expected_game_id!r}")
    assert not unrouted, (
        f"{rel_path} emits rom_types that do not reach its adapter, so a run on that "
        f"variant silently keeps whichever adapter was already loaded:\n"
        + "\n".join(unrouted))


@pytest.mark.parametrize("rel_path,expected_game_id", GB_GBA_MODULES,
                         ids=lambda v: v if isinstance(v, str) else str(v))
def test_every_variant_has_a_display_label(rel_path, expected_game_id):
    """A missing label is cosmetic, but it is the same omission and worth catching together."""
    mod = _load(rel_path)
    missing = [
        f"  {variant!r} -> {mod.rom_type_for_variant(variant)!r}"
        for variant in _variants(mod)
        if mod.rom_type_for_variant(variant) not in _VARIANT_LABEL
    ]
    assert not missing, f"{rel_path} rom_types with no _VARIANT_LABEL entry:\n" + "\n".join(missing)


def test_the_lua_actually_exposed_variants():
    """Self-check: if PROFILES came back empty the tests above would pass vacuously."""
    for rel_path, _ in GB_GBA_MODULES:
        variants = _variants(_load(rel_path))
        assert len(variants) >= 3, f"{rel_path} exposed only {variants} — introspection broke"


def test_no_rom_type_maps_to_a_nonexistent_adapter():
    """Guard the other direction: a typo'd game_id in the table is silently unroutable too."""
    # Imported late: the registry is populated by the adapter modules' import side effects.
    from server.adapters import _REGISTRY
    bad = {rt: gid for rt, gid in _ROM_TYPE_TO_GAME_ID.items() if gid not in _REGISTRY}
    assert not bad, f"rom_types pointing at unregistered adapters: {bad}"


def test_gen2_non_crystal_variants_are_registered():
    """The specific regression, pinned by name so a revert reads as what it is.

    Gold, Silver and Crystal (AP) all routed to None before this fix.
    """
    for rom_type in ("Gold", "Silver", "Crystal (AP)", "gold", "silver", "crystal_ap"):
        assert game_id_for_rom_type(rom_type) == "gen2_crystal", (
            f"{rom_type!r} does not reach the Gen 2 adapter — a run on it would keep the "
            f"default (Gen 3) adapter and persist the wrong game_id")
        assert variant_label(rom_type), f"{rom_type!r} has no display label"
