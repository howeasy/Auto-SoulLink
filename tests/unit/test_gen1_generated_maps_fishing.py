"""Gen 1 maps/subareas and every fishing method, pinned to pret.

Closes two clauses of the `canonical.generated-data` release row:
  maps      area_map.json qualifies against constants/map_constants.asm and the wild data
            (data/wild/grass_water.asm, data/wild/super_rod.asm) of BOTH decomps
  fishing   encounter_tables.json carries Old, Good and Super Rod per title, rebuilt in
            memory from data/wild/good_rod.asm, data/wild/super_rod.asm and the Old Rod
            `lb bc, 5, MAGIKARP` in engine/items/item_effects.asm, and equal to the shipped
            file. Super Rod rates use the ROM scanner's pad-to-ten model so the clean-ROM
            control in test_gen1_rom_content.py holds; Old/Good Rod are generator-only.

Skips when the decomps are not checked out (same rule as test_gen1_items.py).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _load(name: str):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "tools", f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return mod


enc = _load("gen_gen1_encounters")
amap = _load("gen_gen1_area_map")
TITLES = ("red", "blue", "yellow")
RODS = ("Old Rod", "Good Rod", "Super Rod")

pytestmark = pytest.mark.skipif(
    not (os.path.isdir(enc._PRET) and os.path.isdir(enc._PRET_YELLOW)),
    reason="pret decomps not checked out under .cache/pret")


@pytest.fixture(scope="module")
def built():
    out, floors, problems = enc.build(quiet=True)
    assert not problems, problems
    return out, floors


def _shipped() -> dict:
    with open(enc._OUT, encoding="utf-8") as f:
        return json.load(f)


# ── (a) maps / subareas ──────────────────────────────────────────────────────────────────
def test_area_map_qualifies_against_both_decomps():
    with open(amap.AREA_MAP_PATH, encoding="utf-8") as f:
        area_map = json.load(f)
    failures, notes = amap.check(area_map, amap.find_repos())
    assert failures == [], "\n".join(failures)
    # The only wild-data maps without an area are Super-Rod-only towns/indoor maps, and
    # the set is pinned so a change in either direction is a visible decision.
    red_note = next(n for n in notes if n.startswith("pokered:"))
    yellow_note = next(n for n in notes if n.startswith("pokeyellow:"))
    assert red_note.endswith("VIRIDIAN_CITY(1), CERULEAN_CITY(3), VERMILION_CITY(5), "
                             "FUCHSIA_CITY(7), CERULEAN_GYM(65), VERMILION_DOCK(94)"), red_note
    assert yellow_note.endswith("VIRIDIAN_CITY(1), CERULEAN_CITY(3), VERMILION_CITY(5), "
                                "FUCHSIA_CITY(7), VERMILION_DOCK(94)"), yellow_note
    assert any("yellow-only map ids: SUMMER_BEACH_HOUSE(248)" in n for n in notes), notes


# ── (b) the shipped file is what pret says ───────────────────────────────────────────────
def test_in_memory_rebuild_equals_the_shipped_tables(built):
    out, floors = built
    assert enc.diff_against_shipped(out, floors) == []
    assert set(out) == set(TITLES)


# ── (c) every title has every rod, every block sums to 100 ───────────────────────────────
@pytest.mark.parametrize("title", TITLES)
def test_every_rod_method_is_present_and_sums_to_100(title):
    tables = _shipped()[title]
    for rod in RODS:
        areas = [a for a, b in tables.items() if rod in b]
        assert len(areas) == 24, f"{title}/{rod}: {len(areas)} areas"
        for a in areas:
            total = sum(e["rate"] for e in tables[a][rod])
            assert total == 100, f"{title}/{a}/{rod} sums to {total}"
    # One placement rule: Old and Good Rod go wherever there is surf water or a Super Rod
    # group, and nowhere else.
    for a, b in tables.items():
        fishable = "Super Rod" in b or any(m.startswith("Water") for m in b)
        assert ({"Old Rod", "Good Rod"} <= set(b)) == fishable, f"{title}/{a}: {sorted(b)}"


# ── (d) spot checks straight from the asm ────────────────────────────────────────────────
def _rows(entries):
    return {e["name"]: (e["rate"], e["min_level"], e["max_level"]) for e in entries}


@pytest.mark.parametrize("title", TITLES)
def test_old_and_good_rod_match_the_asm(title):
    # engine/items/item_effects.asm ItemUseOldRod: `lb bc, 5, MAGIKARP`
    # data/wild/good_rod.asm GoodRodMons: `db 10, GOLDEEN` / `db 10, POLIWAG`
    route_6 = _shipped()[title]["route_6"]
    assert _rows(route_6["Old Rod"]) == {"Magikarp": (100, 5, 5)}
    assert _rows(route_6["Good Rod"]) == {"Goldeen": (50, 10, 10), "Poliwag": (50, 10, 10)}


def test_red_blue_super_rod_groups_match_the_asm():
    # pokered data/wild/super_rod.asm: ROUTE_6 -> .Group4 = `db 15, KRABBY` / `db 15, SHELLDER`;
    # SAFARI_ZONE_* -> .Group6 = Dratini, Krabby, Psyduck, Slowpoke all L15. The game picks
    # uniformly within a group (ReadSuperRodData), so two entries are 50/50 and four 25 each.
    for title in ("red", "blue"):
        t = _shipped()[title]
        assert _rows(t["route_6"]["Super Rod"]) == {"Krabby": (50, 15, 15), "Shellder": (50, 15, 15)}
        assert _rows(t["safari_zone_center"]["Super Rod"]) == {
            "Dratini": (25, 15, 15), "Krabby": (25, 15, 15),
            "Psyduck": (25, 15, 15), "Slowpoke": (25, 15, 15)}


def test_yellow_super_rod_rows_match_the_asm():
    # pokeyellow data/wild/super_rod.asm line 2:
    #   db PALLET_TOWN, STARYU, 10, TENTACOOL, 10, STARYU, 5, TENTACOOL, 20
    t = _shipped()["yellow"]
    assert _rows(t["pallet_town"]["Super Rod"]) == {"Staryu": (50, 5, 10), "Tentacool": (50, 10, 20)}
    # Cerulean Cave has two rows (1F: Goldeen 25 / Seaking 35,45,55; B1F: 30 / 40,50,60).
    # The lowest map id wins within an area and B1F (0xE3) is below 1F (0xE4), exactly as
    # gen1_rom_scan.build_encounter_tables resolves it; pinned so the choice is visible.
    assert _rows(t["cerulean_cave"]["Super Rod"]) == {"Seaking": (75, 40, 60), "Goldeen": (25, 30, 30)}


# ── (e) the widget shows the rod icon ────────────────────────────────────────────────────
def test_rendered_widget_carries_the_rod_icon():
    from server.adapters.gen1_rby import Gen1Adapter
    from server.server import SLinkServer
    srv = SLinkServer(data_dir=tempfile.mkdtemp())
    srv.state.adapter = srv.adapter = Gen1Adapter(variant="red")
    html = srv._encounter_html("route_6")
    for rod in RODS:
        assert f"🎣 {rod}" in html, f"{rod} lost its icon"
    assert "🎣 Super Super" not in html
