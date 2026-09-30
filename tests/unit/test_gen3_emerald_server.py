"""E3-SERVER: Emerald's title data on the shared Gen3Adapter (docs/gen3_emerald/PLAN.md E3 row).

Emerald keeps game_id gen3_frlge but is its own pairing foundation (gen3_emerald); the adapter
selects the title's data from the rom_type the server forwards. Pairing refusals live in
test_mixed_foundations.py next to the FR/RR ones."""
from __future__ import annotations

import json
import pathlib

import pytest

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


AREA_MAP = json.loads((REPO / "data/games/gen3_emerald/area_map.json").read_text(encoding="utf-8"))
PACK_GIFTS = json.loads((REPO / "data/games/gen3_emerald/write_checkpoint.json")
                        .read_text(encoding="utf-8"))["emerald"]["gift_areas"]["ids"]
# E3-GIFTLINK's named ids for the statics.json gift maps (the gift_<g>_<n> scheme is retired)
GIFTS = {"rustboro_city_devon_corp_2f", "mossdeep_city_stevens_house", "lavaridge_town",
         "route119_weather_institute_2f"}
FIXED_GIFTS = {"mossdeep_city_stevens_house", "lavaridge_town", "route119_weather_institute_2f"}
FIXED_STATICS = {"faraway_island", "birth_island"}          # Mew 26:57, Deoxys 26:58


def test_every_statics_map_has_an_area_id():
    # producer coverage (review cx-361cd02b F2/F3): a map the client cannot name sends "" and
    # _handle_capture drops it, so every catalogued map must be in the area map
    missing = [e["id"] for e in STATICS["entries"] if e["map"] and e["map"] not in AREA_MAP]
    assert missing == []


def test_emerald_gift_areas_are_the_packs_named_ids():
    em, fr = _em(), _fr()
    assert set(PACK_GIFTS) == GIFTS
    for aid in GIFTS:
        assert em.is_gift_area(aid) and not fr.is_gift_area(aid), aid
        assert em.gift_link_area(aid) == aid, aid                   # already a gift area
        assert em.is_fixed_species_gift(aid) is (aid in FIXED_GIFTS), aid  # the fossil is a choice
        assert not em.is_daycare_area(aid), aid
    # Beldum 14:7, Wynaut egg 0:12, Castform 32:1, Mew 26:57, Deoxys 26:58: statics.json's
    # bypass_clauses rows, through the area map
    assert {AREA_MAP[e["map"]] for e in STATICS["entries"]
            if e["bypass_clauses"]} == FIXED_GIFTS | FIXED_STATICS
    # FR's bare ids are Kanto facts, not Emerald ones
    assert fr.is_fixed_species_gift("silph_co_7f") and not em.is_fixed_species_gift("silph_co_7f")
    assert fr.is_gift_area("oaks_lab") and not em.is_gift_area("oaks_lab")


def test_every_bypass_row_is_fixed_under_either_link_id():
    # state.py remaps a gift capture through gift_link_area BEFORE the clause check; a static
    # (ball) capture keeps its area id. Both ids must answer fixed for a bypass row.
    em = _em()
    for e in STATICS["entries"]:
        if e["bypass_clauses"]:
            aid = AREA_MAP[e["map"]]
            assert em.is_fixed_species_gift(aid), (e["id"], aid)
            assert em.is_fixed_species_gift(em.gift_link_area(aid)), (e["id"], aid)


@pytest.mark.parametrize("rom_type", ["firered", "firered_rr", "emerald"])
def test_fixed_gifts_are_gift_areas_and_survive_the_namespace_rewrite(rom_type):
    # the Gen 1 coupling test (test_gen1_gift_areas.py:83-101) ported to both Gen 3 sets: a
    # fixed gift outside the gift set would be renamed gift_<area> and lose its exemption
    from server.adapters import gen3_frlge as g3
    ad = get_adapter("gen3_frlge", is_rr=rom_type.endswith("_rr"), rom_type=rom_type)
    fixed = g3._EMERALD_FIXED_SPECIES_GIFTS if rom_type == "emerald" else g3._FIXED_SPECIES_GIFTS
    assert fixed
    for area in sorted(fixed - FIXED_STATICS):
        assert ad.is_gift_area(area), area
        assert ad.gift_link_area(area) == area, area
        assert ad.is_fixed_species_gift(ad.gift_link_area(area)), area
    for area in sorted(fixed & FIXED_STATICS):           # Mew/Deoxys: static areas, direct form
        assert not ad.is_gift_area(area) and ad.is_fixed_species_gift(area), area


def test_emerald_statics_are_ordinary_areas():
    # FR/LG's precedent (navel_rock): a static legendary's map is an encounter area, clauses on,
    # except the two bypass rows (Mew, Deoxys) whose area holds only that mon
    em = _em()
    for e in STATICS["entries"]:
        if e["kind"] == "static" and e["map"]:
            aid = AREA_MAP[e["map"]]
            assert not em.is_gift_area(aid), (e["id"], aid)
            assert em.is_fixed_species_gift(aid) is (aid in FIXED_STATICS), (e["id"], aid)
    assert AREA_MAP["26:87"] == AREA_MAP["26:75"] == "navel_rock"


# ── end to end through SoulLinkState (shape: test_gen2_fixed_species_gift.py) ─────────────────

def _clause_state(tmp_path, rom_type):
    from server.state import SoulLinkState
    st = SoulLinkState(data_dir=str(tmp_path), species_lock=True,
                       adapter=get_adapter("gen3_frlge", is_rr=False, rom_type=rom_type))
    st.rom_type = rom_type
    st.pokeballs_obtained = {"a": True, "b": True}
    return st


def _pair(st, area_id, species_id, gift):
    st.handle_event("a", {"event": "capture", "key": f"0001:1111:{species_id}",
                          "area_id": area_id, "level": 5, "species_id": species_id, "gift": gift})
    return st.handle_event("b", {"event": "capture", "key": f"0002:2222:{species_id}",
                                 "area_id": area_id, "level": 5, "species_id": species_id,
                                 "gift": gift})


@pytest.mark.parametrize("rom_type,area_id,species_id,gift,linked_as", [
    ("emerald", "mossdeep_city_stevens_house", 374, True, "mossdeep_city_stevens_house"),  # Beldum
    ("emerald", "birth_island", 386, False, "birth_island"),       # Deoxys, a ball capture
    ("emerald", "birth_island", 386, True, "gift_birth_island"),   # ... or flagged a gift
    ("firered", "silph_co_7f", 131, True, "silph_co_7f"),          # FR's Lapras, unchanged
])
def test_a_fixed_gift_pairs_under_the_species_clause(tmp_path, rom_type, area_id, species_id,
                                                     gift, linked_as):
    from server.state import AreaStatus, LinkStatus
    st = _clause_state(tmp_path, rom_type)
    cmds_b = _pair(st, area_id, species_id, gift)
    assert not any(c.get("cmd") == "force_faint" for c in cmds_b), cmds_b
    assert st.area_states.get(linked_as) == AreaStatus.LINKED
    assert len(st.links) == 1 and st.links[0].status == LinkStatus.ALIVE


def test_the_fossil_is_a_choice_gift_and_keeps_the_species_clause(tmp_path):
    # control: Devon Corp 2F (Lileep/Anorith) is a gift area but not fixed, so the same
    # species on both sides still trips the clause
    cmds_b = _pair(_clause_state(tmp_path, "emerald"), "rustboro_city_devon_corp_2f", 345, True)
    assert any(c.get("cmd") == "force_faint" for c in cmds_b), cmds_b


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


def test_emerald_gift_display_names():
    assert _em().area_display_name("mossdeep_city_stevens_house") == "Steven's House"
    assert _em().area_display_name("rustboro_city_devon_corp_2f") == "Devon Corp. 2F"
    assert _em().area_display_name("gift_route_101") == "Gift – Route 101"
    # no Emerald producer emits gift_<g>_<n>; the Kanto ROM-name scrape must not name one
    assert _em().area_display_name("gift_14_7") == "Gift"


def test_the_area_catalog_is_title_aware(tmp_path):
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = _em()
    ids = srv._load_known_area_ids()
    assert "route_101" in ids and "pallet_town" not in ids
    srv.adapter = _fr()
    ids = srv._load_known_area_ids()
    assert "pallet_town" in ids and "route_101" not in ids


# ── F1 (review cx-361cd02b): a restart or rollback rebuilds the title's adapter ─────────────
# Emerald persists game_id gen3_frlge, the default adapter's own, so a rebuild keyed only on
# game_id/is_rr kept a rom_type-less adapter and silently lost the Emerald title data.

def _saved_run(path, rom_type):
    from server.state import SoulLinkState
    st = SoulLinkState(data_dir=str(path))
    st.rom_type = rom_type
    st.is_rr = rom_type.endswith("_rr")
    st.adapter = get_adapter("gen3_frlge", is_rr=st.is_rr, rom_type=rom_type)
    st._save()
    return st


def _assert_title(adapter, rom_type):
    if rom_type == "emerald":
        assert "generation-iii/emerald/1.png" in adapter.sprite_html(1)
        assert adapter.area_pack == "gen3_emerald"
        assert adapter.item_name(375) == "Magma Emblem"
    elif rom_type.endswith("_rr"):
        assert adapter._is_rr and "/static/sprites/rr/1.png" in adapter.sprite_html(1)
        assert adapter.area_pack == "gen3_frlge"
    else:
        assert not adapter._is_rr and adapter.area_pack == "gen3_frlge"
        assert "generation-iii/firered-leafgreen/1.png" in adapter.sprite_html(1)


@pytest.mark.parametrize("rom_type", ["emerald", "firered", "firered_rr"])
def test_a_restart_keeps_the_titles_adapter(tmp_path, rom_type):
    _saved_run(tmp_path, rom_type)
    srv = SLinkServer(data_dir=str(tmp_path))
    assert srv.state.rom_type == rom_type
    _assert_title(srv.adapter, rom_type)
    assert srv.state.adapter is srv.adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("rom_type", ["emerald", "firered", "firered_rr"])
async def test_a_rollback_keeps_the_titles_adapter(tmp_path, rom_type):
    from unittest.mock import AsyncMock
    srv = SLinkServer(data_dir=str(tmp_path / "run"))
    backup_dir = tmp_path / "run" / "backups"
    backup_dir.mkdir(parents=True)
    old = _saved_run(tmp_path / "other", rom_type)
    (backup_dir / "links.backup.1.json").write_bytes(pathlib.Path(old._links_path).read_bytes())
    response = await srv.handle_debug_rollback(AsyncMock(json=AsyncMock(return_value={"slot": 1})))
    assert response.status == 200
    assert srv.state.rom_type == rom_type
    _assert_title(srv.adapter, rom_type)
    assert srv.state.adapter is srv.adapter


def test_hoenn_display_overrides_are_emeralds_own():
    # F7: the Hoenn ids are title-scoped; FR/RR never see them as overrides
    assert _em().area_display_name("mt_pyre") == "Mt. Pyre"
    assert _em().area_display_name("cave_of_origin") == "Cave of Origin"
    assert _fr().area_display_name("cave_of_origin") == "Cave Of Origin"
    assert _em().area_display_name("mt_moon") == _fr().area_display_name("mt_moon") == "Mt. Moon"


def test_a_missing_emerald_pack_does_not_break_the_adapters(tmp_path, monkeypatch):
    # F4: _load_emerald runs at import; a missing Emerald pack file must leave its sets empty,
    # not raise out of `import server.adapters` for every game
    from server.adapters import gen3_frlge
    monkeypatch.setattr(gen3_frlge, "_EMERALD_DIR", str(tmp_path))
    assert gen3_frlge._load_emerald() == (frozenset(), frozenset())
    assert get_adapter("gen1_rby", rom_type="red").game_id == "gen1_rby"


def test_an_unknown_bpee_cartridge_admits_as_the_named_kind():
    # EG3 exit: an Emerald build whose hash and anchors match nothing still routes to the Emerald
    # pack by its header code BPEE (lua/gen3/entry.lua Entry.admit, the named-family fallback)
    from tests.unit.test_gen3_entry import World, _admit, lua_to_py
    world = World(pack="gen3_frlg", title="firered", build=False)
    blank = {0xAC + i: ord(c) for i, c in enumerate("BPEE")}
    got = lua_to_py(_admit(world, rom_hash="ef" * 20, header_code="BPEE",
                           rom_read=lambda o, n: world.lua.table(
                               *[blank.get(int(o) + i, 0) for i in range(int(n))])))
    assert got["admitted_by"] == "header"
    assert (got["pack"], got["title"], got["kind"], got["rom_type"]) == \
        ("gen3_emerald", "emerald", "named", "emerald")
