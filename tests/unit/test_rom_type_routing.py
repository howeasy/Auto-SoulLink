"""Every rom_type a game module can emit must resolve to an adapter.

WHY THIS EXISTS. The legacy `lua/games/gen2_crystal.lua:rom_type_for_variant` returned "Gold", "Silver"
and "Crystal (AP)". None were registered in `_ROM_TYPE_TO_GAME_ID`, so
`game_id_for_rom_type()` returned None, the guard in `server/server.py` never switched the
adapter, and a Gold run continued under whichever adapter was already loaded — the Gen 3
default. Nothing raised, nothing warned, and the wrong `game_id` was then persisted into the
run directory, so the mistake outlived the session that made it.

That is the worst shape a bug can take here: it makes every later measurement lie. A Gold
run would report Gen 3 species names and Gen 3 gift areas, and look like a Gen 2 data
problem rather than a routing one.

The game-module half of this file (driving lua/games/gen2_crystal.lua's
rom_type_for_variant under lupa) retired with that module (P3b.8). Every client that still
emits a rom_type asserts it routes on its own side: Gen 1 in
tests/unit/test_gen1_entry.py::test_rom_type_strings_are_the_ones_the_server_routes_on, Gen 2
in tests/unit/test_gen2_pairing_matrix.py::test_the_rom_types_the_new_client_sends_derive_the_foundation_it_declares.
"""
from server.adapters import _ROM_TYPE_TO_GAME_ID, game_id_for_rom_type, variant_label


def test_no_rom_type_maps_to_a_nonexistent_adapter():
    """Guard the other direction: a typo'd game_id in the table is silently unroutable too."""
    # Imported late: the registry is populated by the adapter modules' import side effects.
    from server.adapters import _REGISTRY
    bad = {rt: gid for rt, gid in _ROM_TYPE_TO_GAME_ID.items() if gid not in _REGISTRY}
    assert not bad, f"rom_types pointing at unregistered adapters: {bad}"


def test_gen2_non_crystal_variants_are_registered():
    """The specific regression, pinned by name so a revert reads as what it is.

    Gold, Silver and Crystal (AP) all routed to None before this fix. U5 (O-22/O-23) later
    moved Gold and Silver's own row to `gen2_gsc` alongside Crystal. Archipelago Crystal is
    the one DELIBERATE exception: owner ruling O-25 refuses it, so it routes to nothing and
    the server refuses its hello by name (never a silent default-adapter fallthrough).
    """
    for rom_type in ("Gold", "Silver", "gold", "silver"):
        assert game_id_for_rom_type(rom_type) == "gen2_gsc", (
            f"{rom_type!r} does not reach the Gen 2 adapter — a run on it would keep the "
            f"default (Gen 3) adapter and persist the wrong game_id")
        assert variant_label(rom_type), f"{rom_type!r} has no display label"
    for rom_type in ("Crystal (AP)", "crystal_ap"):
        assert game_id_for_rom_type(rom_type) is None, f"{rom_type!r} is refused (O-25)"
