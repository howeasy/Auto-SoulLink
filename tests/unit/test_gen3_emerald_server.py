"""E3-SERVER: Emerald's title data on the shared Gen3Adapter (docs/gen3_emerald/PLAN.md E3 row).

Emerald keeps game_id gen3_frlge but is its own pairing foundation (gen3_emerald); the adapter
selects the title's data from the rom_type the server forwards. Pairing refusals live in
test_mixed_foundations.py next to the FR/RR ones."""
from __future__ import annotations

import json
import pathlib

from server.adapters import (
    foundation_for_rom_type,
    get_adapter,
    variant_label,
)
from server.server import SLinkServer

REPO = pathlib.Path(__file__).resolve().parents[2]
STATICS = json.loads((REPO / "data/games/gen3_emerald/statics.json").read_text(encoding="utf-8"))


def _em():
    return get_adapter("gen3_frlge", is_rr=False, rom_type="emerald")


def _fr():
    return get_adapter("gen3_frlge", is_rr=False, rom_type="firered")


def test_emerald_is_its_own_foundation_with_a_label():
    assert foundation_for_rom_type("emerald") == "gen3_emerald"
    assert foundation_for_rom_type("firered") == "gen3_frlg"
    assert variant_label("emerald") == "Emerald"


def test_emerald_fixed_gifts_are_the_statics_bypass_rows():
    em, fr = _em(), _fr()
    # Beldum 14:7, Wynaut egg 0:12, Castform 32:1, Mew 26:57, Deoxys 26:58 (statics.json
    # bypass_clauses=true): none is a wild map, so the client's id would be gift_<g>_<n>.
    bypass = {e["map"] for e in STATICS["entries"] if e["bypass_clauses"]}
    assert bypass == {"14:7", "0:12", "32:1", "26:57", "26:58"}
    for m in bypass:
        aid = "gift_" + m.replace(":", "_")
        assert em.is_fixed_species_gift(aid) and em.is_gift_area(aid), aid
        assert not fr.is_fixed_species_gift(aid), aid
    # FR's bare ids are Kanto facts, not Emerald ones
    assert fr.is_fixed_species_gift("silph_co_7f") and not em.is_fixed_species_gift("silph_co_7f")
    assert fr.is_gift_area("oaks_lab") and not em.is_gift_area("oaks_lab")


def test_the_emerald_starter_route_stays_a_wild_area():
    em = _em()
    assert not em.is_gift_area("route_101") and not em.is_fixed_species_gift("route_101")
    # the starter (gift=true on route_101) links as a standalone gift, a choice gift: clauses on
    assert em.gift_link_area("route_101") == "gift_route_101"
    assert not em.is_fixed_species_gift("gift_route_101")


def test_emerald_has_no_daycare_area_that_could_eat_route_117():
    # The egg is handed over on outdoor Route 117 (pret data/maps/Route117/map.json:65,
    # Route117_EventScript_DaycareMan), a wild route: a daycare id there would consume it.
    em = _em()
    assert not em.is_daycare_area("route_117")
    assert em.gift_link_area("route_117") == "gift_route_117"


def test_emerald_item_overlay():
    assert _em().item_name(375) == "Magma Emblem" and _em().item_name(376) == "Old Sea Map"
    assert _fr().item_name(375) == "Item #375"
    assert _em().item_name(1) == _fr().item_name(1) == "Master Ball"


def test_emerald_sprites_are_emerald_pathed():
    assert "generation-iii/emerald/1.png" in _em().sprite_html(1)
    assert "generation-iii/firered-leafgreen/1.png" in _fr().sprite_html(1)


def test_nature_power_accuracy_is_the_titles_own():
    # pret pokeemerald src/data/battle_moves.h:3479 .accuracy = 95; pokefirered's is 0
    assert _em().move_data(267)["accuracy"] == 95
    assert _fr().move_data(267)["accuracy"] == 0
    assert _em().move_data(33) == _fr().move_data(33)


def test_emerald_gift_display_names_an_emerald_map():
    assert _em().area_display_name("gift_14_7") == "Gift – Mossdeep City Stevens House"


def test_the_area_catalog_is_title_aware(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = _em()
    ids = srv._load_known_area_ids()
    assert "route_101" in ids and "pallet_town" not in ids
    srv.adapter = _fr()
    ids = srv._load_known_area_ids()
    assert "pallet_town" in ids and "route_101" not in ids
