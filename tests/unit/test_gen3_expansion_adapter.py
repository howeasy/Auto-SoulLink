"""Reference-build adapter contract; literals checked against expansion e8bd1cd7."""
import pytest

from server.adapters import (
    foundation_for_rom_type,
    game_id_for_rom_type,
    get_adapter,
    variant_label,
)
from server.adapters.base import GamePresentationAdapter, GameRulesAdapter

ROM_TYPE = "emerald_expansion_28877d73"


def test_reference_build_routes_to_its_own_pack():
    adapter = get_adapter("gen3_exp", rom_type=ROM_TYPE)
    assert isinstance(adapter, (GameRulesAdapter, GamePresentationAdapter))
    assert adapter.game_id == "gen3_exp"
    assert adapter.rom_type == ROM_TYPE
    assert game_id_for_rom_type(ROM_TYPE) == "gen3_exp"
    assert foundation_for_rom_type(ROM_TYPE) == "gen3_exp"
    assert variant_label(ROM_TYPE) == "Emerald Expansion 1.17.0 (28877d73)"
    # Bulbasaur, Pikachu and Pound in pinned include/constants + src/data tables.
    assert adapter.species_name(1) == "Bulbasaur"
    assert adapter.species_types(1) == (13, 4)
    assert adapter.type_name(13) == "Grass"
    assert adapter.evo_family(25) == 172
    assert adapter.move_name(1) == "Pound"


def test_reference_presentation_and_explicit_unsupported_surfaces():
    a = get_adapter("gen3_exp")
    assert a.gender_from_key("00000000:12345678", 1010) == "female"
    assert a.gender_from_key("000000FF:12345678", 678) == "male"
    assert a.gender_from_key("00000000:12345678", 137) == "genderless"
    assert a.to_national_dex(1572) == 970
    assert a.species_name(1572) == "Glimmora"
    assert a.species_abilities(1) == (65, 0, 34)
    assert a.ability_name(318) == "Spicy Spray"
    assert a.item_name(1) == "Poké Ball"  # vanilla item 1 is Master Ball
    assert a.item_name(873) == "Glimmoranite"
    assert a.move_data(847) == {"name": "Malignant Chain", "type_id": 4,
                              "type_name": "Poison", "power": 100, "accuracy": 100,
                              "pp": 5, "split": 1}
    assert a.move_data(1)["split"] == 0
    assert a.move_data(14)["split"] == 2  # Swords Dance
    assert a.sprite_src(1572).endswith("/970.png")
    assert '/970.png' in a.sprite_html(1572)
    assert a.form_sprite_id(1572) is None
    assert a.gym_badge_slugs(ROM_TYPE)[0] == (17, "Stone Badge")
    assert a.gym_badge_slugs(ROM_TYPE)[-1] == (24, "Rain Badge")
    assert a.calc_profile() is None and a.calc_stats({}) is None
    assert a.calc_nature("00000000:00000000") is None
    assert a.calc_name("species", "Mr. Mime") == "Mr. Mime"
    assert a.encounter_table("route_101") is None
    assert a.trainers_for_area("route_101") == []
    assert a.trainer_party(1) == [] and a.trainer_brief(1) is None
    assert a.trainer_info(1) == ("", "")
    assert a.rival_trainer_ids() == set()
    assert not a.supports_info_panel() and not a.supports_explode_mode()
    assert not a.native_trade_ui()
    assert a.party_blob_size() == 100 and a.memorial_box_index == 13
    assert a.is_valid_mon_key("12345678:87654321")
    assert a.parse_ot_id("12345678:87654321") == "87654321"
    assert a.status_token(0x88) == "TOX"
    assert a.gift_link_area("route_101") == "gift_route_101"
    assert not a.is_fixed_species_gift("gift_beldum")  # no unextracted static policy
    assert a.area_pack == "gen3_exp/28877d73"
    assert a.pairing_kind("companion") == "companion"


@pytest.mark.parametrize("value", [0, 9999, -1])
def test_unknown_tables_have_no_vanilla_fallback(value):
    a = get_adapter("gen3_exp")
    assert a.to_national_dex(value) == 0
    assert a.species_types(value) is None
    assert a.move_data(value) is None
    assert a.sprite_src(value) == ""


def test_shiny_modifier_is_an_xor_and_key_only_gap_is_explicit():
    a = get_adapter("gen3_exp")
    assert a.is_shiny("00000007:00000000")
    assert not a.is_shiny("00000008:00000000")
    assert a.is_shiny("00000008:00000000", shiny_modifier=1)
    assert not a.is_shiny("00000007:00000000", shiny_modifier=1)
    assert not a.is_shiny("bad", shiny_modifier=1)


def test_masked_party_record_feeds_only_expansion_facts():
    import struct

    from server.adapters.gen3_codec import decode_party_mon_masked
    from tests.unit.test_gen3_expansion_masks import EXPANSION_LAYOUT

    # PID=OTID=0: identity substruct order and XOR key zero. Source constants:
    # species.h:1069 Hisuian Sneasel=999; moves.h Malignant Chain=847.
    # Place unrelated bitfields above species/move IDs to falsify vanilla decode.
    raw = bytearray(100)
    raw[0x08:0x12] = b"\xff" * 10
    raw[0x14:0x1b] = b"\xff" * 7
    raw[0x13] = 2
    struct.pack_into("<H", raw, 0x1e, 1 << 14)  # shinyModifier
    struct.pack_into("<HH", raw, 0x20, 999 | (3 << 11), 873 | (7 << 10))
    struct.pack_into("<4H", raw, 0x2c, 847 | (3 << 11), 14 | (3 << 11), 1, 0)
    struct.pack_into("<I", raw, 0x4c, 2 << 29)  # hidden ability selector
    struct.pack_into("<H", raw, 0x1c, sum(struct.unpack_from("<24H", raw, 0x20)) & 0xffff)
    mon = decode_party_mon_masked(raw, layout=EXPANSION_LAYOUT)
    a = get_adapter("gen3_exp")
    assert mon["species"] == 999 and mon["held_item"] == 873
    assert a.species_name(mon["species"]) == "Sneasel"
    assert a.item_name(mon["held_item"]) == "Glimmoranite"
    assert [a.move_name(move) for move in mon["moves"]] == [
        "Malignant Chain", "Swords Dance", "Pound", "",
    ]
    assert len(a.species_abilities(mon["species"])) == 3
    assert a.is_shiny(f"{mon['personality']:08X}:{mon['ot_id']:08X}",
                      shiny_modifier=mon["shiny_modifier"]) is False
    # No encoder receives a masked record: this adapter is read-only.


@pytest.mark.asyncio
@pytest.mark.parametrize("other", ["emerald", "firered", "leafgreen", "firered_rr"])
@pytest.mark.parametrize("exp_first", [True, False])
async def test_expansion_refuses_mixed_foundations_without_mutating_run(tmp_path, other, exp_first):
    from server.server import SLinkServer
    from tests.unit.test_mixed_foundations import _hello, _refused, _session, _snapshot

    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    first, second = (ROM_TYPE, other) if exp_first else (other, ROM_TYPE)
    try:
        assert not _refused(await send(_hello("a", {"rom_type": first, "artifact_kind": "clean"})))
        before = _snapshot(srv)
        assert _refused(await send(_hello("b", {"rom_type": second, "artifact_kind": "clean"})))
        assert _snapshot(srv) == before
    finally:
        await close()


@pytest.mark.asyncio
async def test_reference_pairs_with_itself_and_unknown_build_stays_unrouted(tmp_path):
    from server.server import SLinkServer
    from tests.unit.test_mixed_foundations import _hello, _refused, _session

    assert game_id_for_rom_type("emerald_expansion_deadbeef") is None
    assert foundation_for_rom_type("emerald_expansion_deadbeef") is None
    srv = SLinkServer(data_dir=str(tmp_path))
    send, close = await _session(srv)
    try:
        for player in ("a", "b"):
            reply = await send(_hello(player, {"rom_type": ROM_TYPE, "artifact_kind": "clean"}))
            assert not _refused(reply) and not srv.state.identity_error.get(player)
        assert srv.adapter.game_id == "gen3_exp"
    finally:
        await close()


def test_expansion_data_check_compares_without_rewriting(tmp_path, monkeypatch):
    import json
    import sys

    from tests.unit.test_extract_expansion_data import synthetic_expansion
    from tools import extract_expansion_data as ex

    rom, layout, _ = synthetic_expansion()
    rom_path, layout_path, output = tmp_path / "input.gba", tmp_path / "layout.json", tmp_path / "data.json"
    rom_path.write_bytes(rom)
    layout_path.write_text(json.dumps(layout))
    (tmp_path / "charmap.txt").write_text("'A' = BB\n'B' = BC\n")
    argv = ["extract", "--rom", str(rom_path), "--source", str(tmp_path),
            "--layout", str(layout_path), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    ex.main()
    original = output.read_bytes()
    monkeypatch.setattr(sys, "argv", [*argv, "--check"])
    ex.main()
    assert output.read_bytes() == original
    output.write_text("corrupted pack")
    with pytest.raises(ex.ExtractionError, match="differs"):
        ex.main()
    assert output.read_text() == "corrupted pack"
    output.unlink()
    with pytest.raises(ex.ExtractionError, match="missing"):
        ex.main()
    assert not output.exists()


# ── F1/F2 (review): OT keys carry the full 32-bit OTID (TID low16, SID high16) ──────────────

def test_ot_key_parser_is_the_shared_one_gen3_frlge_uses():
    # F1: no local reimplementation that could silently drop the SID half.
    from server.adapters.gen3_expansion import _parse_pid_otid_key as exp_parse
    from server.adapters.gen3_frlge import _parse_pid_otid_key as frlg_parse

    assert exp_parse is frlg_parse
    assert exp_parse("00000000:0008000C") == (0, 0x0008000C)


def test_shiny_with_a_high_half_ot_matches_the_hand_computed_formula():
    # F2: OT 0x0008000C -> TID=0x000C, SID=0x0008. personality=0 -> pid_hi=pid_lo=0.
    # (tid ^ sid ^ pid_hi ^ pid_lo) = 0x000C ^ 0x0008 = 0x0004 < 8 -> shiny.
    # A parser that dropped SID (treated ot_id as a bare 16-bit trainer id, sid=0)
    # would compute 0x000C = 12, not < 8, and get this wrong.
    tid, sid, pid_hi, pid_lo = 0x000C, 0x0008, 0, 0
    expected = (tid ^ sid ^ pid_hi ^ pid_lo) < 8
    assert expected is True
    a = get_adapter("gen3_exp")
    assert a.is_shiny("00000000:0008000C") is expected


# ── F3: move_data must not KeyError on a missing/unknown move category ──────────────────────

def test_move_data_defaults_split_to_status_when_category_is_missing_or_unknown():
    a = get_adapter("gen3_exp")
    a._moves[90001] = {"name": "No Category Move", "type": 0, "power": 40,
                        "accuracy": 100, "pp": 15}  # no "category" key at all
    a._moves[90002] = {"name": "Weird Category Move", "type": 0, "power": 40,
                        "accuracy": 100, "pp": 15, "category": 99}  # not in {1, 2, 3}
    assert a.move_data(90001)["split"] == 2
    assert a.move_data(90002)["split"] == 2


# ── F6: sentinel/placeholder pack names never surface as display names ──────────────────────

def test_name_helper_falls_back_on_every_sentinel_spelling_in_the_pack():
    # Literal id-0 sentinels shipped in data/games/gen3_exp/28877d73/data.json.
    from server.adapters.gen3_expansion import _name

    assert _name({"name": "??????????"}, "Species #0") == "Species #0"
    assert _name({"name": "-"}, "Move #0") == "Move #0"
    assert _name({"name": "????????"}, "Item #0") == "Item #0"
    assert _name({"name": "-------"}, "Ability #0") == "Ability #0"
    assert _name({}, "fallback") == "fallback"
    assert _name({"name": "Bulbasaur"}, "Species #1") == "Bulbasaur"


def test_sentinel_names_never_surface_through_the_adapter():
    a = get_adapter("gen3_exp")
    # species id 0 is the pack's "??????????" sentinel row.
    assert a.species_name(0) == "Species #0"
    # abilities 314 and 317 are "-------" sentinels at non-zero ids in the shipped pack.
    assert a.ability_name(314) == "Ability #314"
    assert a.ability_name(317) == "Ability #317"


# ── F4: the debug area catalog has no cross-game fallback ───────────────────────────────────

@pytest.mark.asyncio
async def test_expansion_debug_area_catalog_never_borrows_frlges(tmp_path):
    import json
    from pathlib import Path

    from aiohttp.test_utils import TestClient, TestServer

    from server.server import SLinkServer, build_app

    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = get_adapter("gen3_exp")
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/api/debug/manual_link_data")).json()
    finally:
        await client.close()
    # gen3_exp ships its own area_map.json (data/games/gen3_exp/28877d73/area_map.json):
    # the catalog is that pack's own Hoenn-first id set, plus the always-appended "gift".
    own_map = json.loads(
        (Path(__file__).resolve().parents[2] / "data/games/gen3_exp/28877d73/area_map.json")
        .read_text(encoding="utf-8")
    )
    expected = sorted({v for v in own_map.values() if isinstance(v, str)} | {"gift"})
    assert body["area_ids"] == expected
    # Never a FR/LG-only (Kanto/Sevii) id silently borrowed from gen3_frlge's catalog.
    for kanto_only in ("cinnabar_lab", "saffron_dojo", "digletts_cave"):
        assert kanto_only not in body["area_ids"]


@pytest.mark.asyncio
async def test_expansion_debug_area_catalog_is_empty_without_a_shipped_map(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from server.adapters.gen3_expansion import Gen3ExpansionAdapter
    from server.server import SLinkServer, build_app
    from server.state import AreaStatus

    # data/games/gen3_exp/ (the parent of the 28877d73 build dir) exists but ships no
    # area_map*.json of its own: a real "no map" directory, not a nonexistent one (which
    # would trip _load_known_area_ids' gen3_frlge fallback instead of testing the [] path).
    monkeypatch.setattr(Gen3ExpansionAdapter, "area_pack", property(lambda self: "gen3_exp"))
    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = get_adapter("gen3_exp")
    srv.state.area_states["some_visited_area"] = AreaStatus.LINKED
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/api/debug/manual_link_data")).json()
    finally:
        await client.close()
    # No shipped catalog: only "gift" (always appended) plus areas the run itself entered.
    assert body["area_ids"] == ["gift", "some_visited_area"]
    assert "pallet_town" not in body["area_ids"]


@pytest.mark.asyncio
async def test_a_vanilla_game_still_gets_its_own_area_catalog(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from server.server import SLinkServer, build_app

    srv = SLinkServer(data_dir=str(tmp_path))
    srv.adapter = get_adapter("gen3_frlge", is_rr=False, rom_type="firered")
    client = TestClient(TestServer(build_app(srv)))
    await client.start_server()
    try:
        body = await (await client.get("/api/debug/manual_link_data")).json()
    finally:
        await client.close()
    assert "pallet_town" in body["area_ids"]
    assert "route_101" not in body["area_ids"]  # that's Emerald's own map, not FR/LG's
