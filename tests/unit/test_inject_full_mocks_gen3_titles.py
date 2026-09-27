"""CARD UI-MOCKS-G3 -- tools/inject_full_mocks.py's new `--title` for `--game gen3`.

The coordinator needs to visually check the Gen 3 trainer panel, Upcoming Key Trainers
and the calc Prep tab on every Gen 3 title (firered_rr, frlg, emerald), not just Radical
Red. This pins the areas the injector parks each player in at the end of a run: they must
be real areas for that title's own data pack and have at least one key trainer, checked
through the REAL `Gen3Adapter` (the class the server itself instantiates), not a
re-implementation of its area/trainer lookups.

It also pins a fact discovered while picking those areas: `Gen3Adapter.encounter_table`
returns None for every CLEAN (non-RR, non-ingested) FR/LG or Emerald cartridge, on every
area -- there is no shipped wild-encounter data for a clean vanilla or Emerald cartridge
anywhere in this repo, only `data/games/gen3_frlge/rr_encounters.json`, which is gated on
`is_rr`. So the "wild encounters" panel is legitimately empty for `--title frlg` and
`--title emerald` regardless of area choice; only `--title firered_rr` can show it. That
is real per-cartridge server behaviour, not a mock-data gap.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INJECTOR = os.path.join(_REPO, "tools", "inject_full_mocks.py")


def _load_injector():
    # tools/ is not a package; load the script as a module so its cast and helpers are ours,
    # the same pattern tests/unit/populated_server.py uses to drive it.
    spec = importlib.util.spec_from_file_location("inject_full_mocks_gen3_titles", _INJECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _area_ids(pack_dir: str) -> set[str]:
    path = os.path.join(_REPO, "data", "games", pack_dir, "area_map.json")
    with open(path, encoding="utf-8") as f:
        return set(json.load(f).values())


# title -> (rom_type sent by player a, by player b, is_rr, the data/games/<pack> the
# server's own routing table (server/adapters/__init__.py game_id_for_rom_type) uses for it).
GEN3_TITLES = {
    "firered_rr": ("firered_rr", "firered_rr", True, "gen3_frlge"),
    "frlg":       ("firered", "leafgreen", False, "gen3_frlge"),
    "emerald":    ("emerald", "emerald", False, "gen3_emerald"),
}


@pytest.mark.parametrize("title", sorted(GEN3_TITLES))
def test_rom_types_sent_per_title(title):
    """The hello rom_type each side sends must be a string server/adapters/__init__.py
    _ROM_TYPE_TO_GAME_ID actually routes to gen3_frlge, or the run never switches adapter."""
    from server.adapters import game_id_for_rom_type

    mod = _load_injector()
    mod.GAME, mod.TITLE = "gen3", title
    rom_a, rom_b, _, _ = GEN3_TITLES[title]

    assert mod._rom_type("a") == rom_a
    assert mod._rom_type("b") == rom_b
    assert game_id_for_rom_type(rom_a) == "gen3_frlge"
    assert game_id_for_rom_type(rom_b) == "gen3_frlge"


@pytest.mark.parametrize("title", sorted(GEN3_TITLES))
def test_final_areas_exist_and_have_key_trainers(title):
    """Both final areas must be real areas for this title's data pack and have at least
    one key trainer, via the real Gen3Adapter.trainers_for_area -- the method the
    Upcoming Key Trainers widget calls (server/server.py _trainer_panel_html)."""
    from server.adapters.gen3_frlge import Gen3Adapter

    mod = _load_injector()
    mod.GAME, mod.TITLE = "gen3", title
    rom_a, rom_b, is_rr, pack = GEN3_TITLES[title]
    final_a, final_b = mod._final_areas()
    assert final_a != final_b, f"{title}: final areas must differ for the split view"

    known_areas = _area_ids(pack)
    for area, rom_type in ((final_a, rom_a), (final_b, rom_b)):
        assert area in known_areas, (
            f"{title}: {area!r} is not a real area in data/games/{pack}/area_map.json"
        )
        adapter = Gen3Adapter(is_rr=is_rr, rom_type=rom_type)
        assert adapter.trainers_for_area(area), (
            f"{title}/{rom_type}: {area!r} has no key trainers -- "
            "Upcoming Key Trainers would render empty"
        )


def test_emerald_cast_areas_are_real_hoenn_areas():
    """The whole Emerald cast (not just the final areas) uses real data/games/gen3_emerald
    area ids -- Kanto ids like the default cast's 'route1' don't exist on that foundation."""
    mod = _load_injector()
    mod.GAME, mod.TITLE = "gen3", "emerald"
    known_areas = _area_ids("gen3_emerald")

    areas = {a for a, _, _ in mod._pairs()}
    areas.add(mod._pending()[0])
    areas.add(mod._dead_zone()[0])
    areas.add(mod._boxed()[0])
    areas.update(mod._final_areas())

    missing = areas - known_areas
    assert not missing, f"emerald cast uses area ids not in area_map.json: {sorted(missing)}"


def test_clean_vanilla_titles_show_wild_encounters_at_the_mock_standing_areas():
    """Card WILD-VANILLA: clean FR/LG and Emerald now ship pret-derived wild tables, so the
    mock's final standing areas render a real Wild panel on every Gen 3 title."""
    from server.adapters.gen3_frlge import Gen3Adapter

    for rom_type, areas in (("firered", ("route_22", "cerulean_city")),
                            ("leafgreen", ("route_22", "cerulean_city")),
                            ("emerald", ("route_103", "route_110"))):
        adapter = Gen3Adapter(is_rr=False, rom_type=rom_type)
        for area in areas:
            assert adapter.encounter_table(area), f"{rom_type}/{area}: no wild table"


def test_firered_rr_default_title_is_unchanged():
    """--title defaults to firered_rr for gen3 (no flag = old behaviour): the pre-existing
    cast and final areas must be exactly what they were before --title existed for gen3."""
    mod = _load_injector()
    mod.GAME = "gen3"  # mod.TITLE left at its module default ("crystal", gen2's default --
    # unused here, since firered_rr is the fallback whenever TITLE isn't "frlg"/"emerald").

    assert mod._rom_type("a") == "firered_rr"
    assert mod._rom_type("b") == "firered_rr"
    assert mod._pairs() is mod.PAIRS
    assert mod._final_areas() == ("route_22", "cerulean_city")
