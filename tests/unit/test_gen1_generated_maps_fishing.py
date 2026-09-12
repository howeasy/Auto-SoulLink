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
    # Every map that carries wild data of any method has an area: the Super-Rod-only towns
    # and the two indoor fishing maps fold into their cities (Cerulean Gym -> cerulean_city,
    # Vermilion Dock -> vermilion_city), the same policy that folds the Fighting Dojo into
    # saffron_city. Pinned so an unmapped fishable map is a visible failure, not a note.
    for prefix in ("pokered:", "pokeyellow:"):
        note = next(n for n in notes if n.startswith(prefix))
        assert note.endswith("(fishing there is not shown): none"), note
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
        areas = [a for a, b in tables.items() if any(m.startswith(rod) for m in b)]
        assert len(areas) == 28, f"{title}/{rod}: {len(areas)} areas"
        for a in areas:
            for method, entries in tables[a].items():
                if method.startswith(rod):
                    total = sum(e["rate"] for e in entries)
                    assert total == 100, f"{title}/{a}/{method} sums to {total}"
    # One placement rule: Old and Good Rod go wherever there is surf water or a Super Rod
    # group, and nowhere else.
    for a, b in tables.items():
        fishable = any(m.startswith(("Super Rod", "Water")) for m in b)
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
    # and engine/items/super_rod.asm GenerateRandomFishingEncounter compares one random byte
    # to $66/$B2/$E5, so the four slots weigh 102/76/51/27 of 256: Staryu (slots 1+3) 60,
    # Tentacool (slots 2+4) 40. Not uniform, unlike Red and Blue.
    t = _shipped()["yellow"]
    assert _rows(t["pallet_town"]["Super Rod"]) == {"Staryu": (60, 5, 10), "Tentacool": (40, 10, 20)}
    assert enc.parse_super_rod_thresholds(enc._PRET_YELLOW) == (0x66, 0xB2, 0xE5)
    assert enc.parse_super_rod_thresholds(enc._PRET) is None
    # Cerulean Cave has two rows (1F: Goldeen 25 / Seaking 35,45,55; B1F: 30 / 40,50,60) and
    # Vermilion City two (city: Tentacool 15,20,10 / Horsea 5; dock: Tentacool 10,15 / Staryu
    # 15 / Shellder 10). Each fishing map in a multi-map area keeps its own labelled row --
    # the wild floor where there is one, else the map constant's tail -- so nothing is lost
    # to first-wins, and the rates are the Yellow slot weights aggregated per species.
    assert _rows(t["cerulean_cave"]["Super Rod 1F"]) == {"Seaking": (60, 35, 55), "Goldeen": (40, 25, 25)}
    assert _rows(t["cerulean_cave"]["Super Rod B1F"]) == {"Seaking": (60, 40, 60), "Goldeen": (40, 30, 30)}
    assert _rows(t["vermilion_city"]["Super Rod"]) == {"Tentacool": (90, 10, 20), "Horsea": (10, 5, 5)}
    assert _rows(t["vermilion_city"]["Super Rod Dock"]) == {"Tentacool": (70, 10, 15), "Staryu": (20, 15, 15), "Shellder": (10, 10, 10)}
    assert "Super Rod" not in t["cerulean_cave"]


def test_super_rod_weights_are_the_titles_own_and_the_pin_bites(monkeypatch):
    """Red/Blue reject-sample uniformly; Yellow thresholds one byte. A scanner pin that drifts
    from the asm is refused by the generator, and a wrong group size is refused by the scanner."""
    from server.adapters import gen1_rom_scan as scan
    assert scan.super_rod_rates("red", 2) == (50, 50) and scan.super_rod_rates("blue", 4) == (25, 25, 25, 25)
    assert scan.super_rod_rates("red", 3) == (34, 33, 33)
    assert scan.super_rod_rates("yellow", 4) == (40, 30, 20, 10)
    with pytest.raises(scan.RomScanError):
        scan.super_rod_rates("yellow", 3)
    group = [(10, "STARYU"), (10, "TENTACOOL"), (5, "STARYU"), (20, "TENTACOOL")]
    assert enc.super_rod_rates("yellow", enc._PRET_YELLOW, group) == [40, 30, 20, 10]
    monkeypatch.setattr(scan, "YELLOW_SUPER_ROD_THRESHOLDS", (0x40, 0x80, 0xC0))
    with pytest.raises(ValueError, match="differ from the scanner pin"):
        enc.super_rod_rates("yellow", enc._PRET_YELLOW, group)
    with pytest.raises(ValueError, match="unexpected super rod selection routine"):
        enc.super_rod_rates("red", enc._PRET_YELLOW, group)


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
