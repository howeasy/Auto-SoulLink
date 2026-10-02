"""tools/gen4_routes.py: path-finding on map data (no emulator). Synthetic grids always run; the
real ROM/pret/save cases skip by name when an input is absent and fail when present but wrong
(tests/TESTING.md)."""

import json
import re
import struct
from pathlib import Path

import pytest

from tests.unit.test_gen4_evidence import model_surface  # noqa: F401
from tools import gen4_routes as gr

pytestmark = pytest.mark.usefixtures("model_surface")

ROM, PRET, SAVE = gr.DEFAULT_ROM, gr.DEFAULT_PRET, gr.DEFAULT_SAVE


def _world(rows, soft=(), blocked=(), water=frozenset(), warps=(), scripts=None, header=7):
    """One 32x32 land cell from ascii rows: '#' collision, '.' floor, 'g' encounter grass,
    '~' surfable water; header id 7 (named "TST")."""
    words = [0x8006] * 1024
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            words[y * 32 + x] = {"#": 0x8006, ".": 0x0000, "g": 0x0002, "~": 0x0015}[ch]
    return gr.World(
        1,
        1,
        [header],
        [0],
        {0: tuple(words)},
        set(blocked),
        set(soft),
        water or frozenset({0x15}),
        {header: "TST"},
        frozenset(warps),
        dict(scripts or {}),
    )


def _start(x, y):
    return {"map": 7, "x": x, "y": y, "dir": 1}


def _check_never_blocked(world, route):
    for x, y in gr.replay(world, route)[1:]:
        assert world.walkable(x, y), f"route crosses blocked tile {(x, y)}"
        assert (x, y) not in world.blocked


ROWS = [
    "################",
    "#..............#",
    "#.#####.######.#",
    "#.#...#.#....#.#",
    "#.#.#.#.#.##.#.#",
    "#...#...#.ggg..#",
    "################",
]


def test_path_reaches_grass_and_never_crosses_a_blocked_tile():
    w = _world(ROWS)
    r = gr.plan_route(w, _start(1, 1))
    _check_never_blocked(w, r)
    end = gr.replay(w, r)[-1]
    assert w.is_grass(*end)
    # the pace partner is a horizontal grass neighbour
    a, b = r["grass"]["pace"]["a"], r["grass"]["pace"]["b"]
    assert tuple(a) == end and w.is_grass(*b) and abs(a[0] - b[0]) == 1 and a[1] == b[1]
    assert r["tiles"] == len(gr.replay(w, r)) - 1


def test_unrelated_event_tiles_are_hard_blocked():
    w = _world(ROWS, blocked={(7, 1), (7, 2)})  # an NPC box plugging the only corridor east
    with pytest.raises(gr.RouteError) as e:
        gr.plan_route(w, _start(1, 1))
    assert e.value.reason == "no_grass_reachable"


def test_coord_event_is_crossed_only_when_unavoidable():
    # two corridors to the grass: the direct one carries a coord event, the detour is longer
    rows = [
        "################",
        "#.....gg.......#",
        "#.############.#",
        "#..............#",
        "################",
    ]
    w = _world(rows, soft={(3, 1), (4, 1)}, scripts={(3, 1): ("T20_002",), (4, 1): ("T20_002",)})
    r = gr.plan_route(w, _start(1, 1))
    _check_never_blocked(w, r)
    assert r["soft_events"] == []  # the long way round beats a coord-event crossing
    assert gr.replay(w, r)[-1] == (7, 1)
    # when the only way is through the event it is taken, and the scriptIds travel with the route
    w2 = _world(["########", "#..gg###", "########"], soft={(2, 1)}, scripts={(2, 1): ("R29_001",)})
    r2 = gr.plan_route(w2, _start(1, 1))
    assert r2["soft_events"] == [{"x": 2, "y": 1, "scriptIds": ["R29_001"]}]


def test_wrong_map_id_is_refused():
    w = _world(ROWS)
    bad = _start(1, 1)
    bad["map"] = 8
    with pytest.raises(gr.RouteError) as e:
        gr.plan_route(w, bad)
    assert e.value.reason == "map_mismatch"


def test_start_off_the_map_is_refused():
    w = _world(ROWS)
    w.lands[0] = gr.VOID_LAND
    with pytest.raises(gr.RouteError) as e:
        gr.plan_route(w, _start(1, 1))
    assert e.value.reason == "start_off_map"


def test_grass_without_a_pace_partner_is_skipped():
    # a lone grass tile has no horizontal grass neighbour; the pair further on is chosen
    w = _world(["#########", "#.g.gg..#", "#########"])
    r = gr.plan_route(w, _start(1, 1))
    assert gr.replay(w, r)[-1] == (4, 1) and r["grass"]["pace"]["b"] == [5, 1]


def test_edge_split_is_a_segment_end():
    w = _world(["#########", "#..ggg..#", "#########"])
    r = gr.plan_route(w, _start(1, 1))
    tiles = gr.replay(w, r)
    # walk: (1,1)->(2,1) floor, (3,1) first grass: the edge (2,1) must end a segment
    idx = r["grass_edge_after_step"]
    assert idx is not None
    last = r["steps"][idx]["to"]
    assert (last["x"], last["y"]) == (2, 1) and not w.is_grass(2, 1)
    assert tiles[-1] == (3, 1)


def test_surfable_water_is_blocked_not_priced():
    # behaviour 0x15 is surfable water: the game gates it behind Surf
    # (Field_PlayerCanSurfOnTile, asm/overlay_01_021F1AFC.s:763-780; the blocked predicate
    # sub_02060E54, asm/unk_0205FD20.s:2155-2181), so a water tile is impassable on foot.
    # Pricing it instead would plan a swim the walker cannot make.
    w = _world(["##########", "#........#", "#~~~~~~~~#", "#...gg...#", "##########"])
    assert w.is_water(4, 2) and not w.walkable(4, 2)
    with pytest.raises(gr.RouteError) as e:
        gr.plan_route(w, _start(1, 1))
    assert e.value.reason == "no_grass_reachable"
    # and a route that does exist never reports a water tile
    ok = _world(["#########", "#.......#", "#..~~~..#", "#...gg..#", "#########"])
    r = gr.plan_route(ok, _start(1, 1))
    assert r["water_tiles"] == [] and gr.replay(ok, r)[-1] == (4, 3)


def test_grass_crossed_on_the_approach_is_reported():
    # a lone grass tile on the way to the pace pair is legal, and a wild encounter can fire
    # there, so the route has to name those tiles (the Lua polls the battle chain for them)
    w = _world(["##########", "#.g..gg..#", "##########"])
    r = gr.plan_route(w, _start(1, 1))
    assert r["approach_grass"] == [[2, 1]]
    assert r["grass"]["tile"]["x"] == 5  # the first grass with a horizontal partner
    # a start that is already on the goal grass has no approach to report
    assert gr.plan_route(w, _start(6, 1))["approach_grass"] == []


def test_the_start_tile_exemption_does_not_mutate_the_world():
    w = _world(ROWS, blocked={(1, 1)})
    before = set(w.blocked)
    r = gr.plan_route(w, _start(1, 1))
    assert w.blocked == before and (1, 1) in w.blocked  # the world's events are untouched
    _check_never_blocked(w, r)
    assert gr.replay(w, r)[-1] == (12, 5)


def test_an_exhausted_search_budget_is_its_own_refusal():
    w = _world(ROWS)
    with pytest.raises(gr.RouteError) as e:
        gr._search(w, (1, 1), lambda t: False, limit=5)
    assert e.value.reason == "search_budget"
    assert gr.plan_route(w, _start(1, 1))["tiles"] > 0  # the default budget is not the limit


def test_terrain_layout_guard_refuses_a_misaligned_member():
    body = struct.pack("<4I", 0x800, 0x10, 0x20, 0x30) + struct.pack("<HH", 0x1234, 0)
    good = body + bytes(0x800 + 0x10 + 0x20 + 0x30)
    assert len(gr._terrain(good, 1)) == 1024
    extra = (
        struct.pack("<4I", 0x800, 0x10, 0x20, 0x30)
        + struct.pack("<HH", 0x1234, 8)
        + bytes(8 + 0x800 + 0x10 + 0x20 + 0x30)
    )
    assert len(gr._terrain(extra, 2)) == 1024
    with pytest.raises(gr.FixtureError):
        gr._terrain(good + b"\0", 3)  # length identity broken
    with pytest.raises(gr.FixtureError):
        gr._terrain(b"\0" * 8 + good[8:], 4)  # bad terrain size


def test_parse_result_takes_the_last_result_line():
    log = (
        "[f1] x\n[f9] RESULT RESYNC map=60 x=1 y=2 dir=1 state=C:/a.State\n"
        "[f10] RESULT BATTLE phase=pace species=PIDGEY(16) level=2 map=33 x=665 y=404"
    )
    r = gr.parse_result(log)
    assert r["status"] == "BATTLE"
    assert "phase=pace" in r["detail"] and "species=PIDGEY(16)" in r["detail"]
    assert gr.parse_result("nothing")["status"] == "NO_RESULT"
    # an encounter on the approach is still a battle, not a resync
    assert gr.parse_result("[f1] RESULT BATTLE phase=approach species=PIDGEY(16)")["status"] == (
        "BATTLE"
    )


def test_save_position_absent_is_a_named_skip(tmp_path):
    with pytest.raises(gr.RomAbsent):
        gr.save_position(tmp_path / "nope.SaveRAM")


# --- errands (enter / talk / exit a house) ----------------------------------------------------------
def _errand():
    outer = _world(["#######", "#.....#", "#.....#", "#######"], blocked={(4, 3)})
    house = _world(["#######", "#.....#", "#.....#", "#######"], blocked={(4, 1), (2, 3)}, header=8)
    return outer, gr.Errand(8, 7, house, (4, 3), (2, 3), (4, 1))


def test_errand_enter_ends_with_a_flagged_door_step():
    outer, err = _errand()
    r = gr.plan_errand(outer, err, "enter", _start(1, 1))
    last = r["steps"][-1]
    assert last["warp"] and last["dir"] == "Down" and last["to"]["map"] == 8
    tiles = gr.replay(outer, {**r, "steps": r["steps"][:-1]})
    assert tiles[-1] == (4, 2)  # the tile in front of the door
    _check_never_blocked(outer, {**r, "steps": r["steps"][:-1]})


def test_errand_talk_faces_the_npc_and_exit_leaves_by_the_door():
    _, err = _errand()
    t = gr.plan_errand(err.house, err, "talk", {"map": 8, "x": 1, "y": 2, "dir": 0})
    end = gr.replay(err.house, t)[-1]
    assert abs(end[0] - 4) + abs(end[1] - 1) == 1 and "warp" not in json.dumps(t["steps"])
    assert gr.DIRS[t["talk"]["face"]] == (4 - end[0], 1 - end[1])  # toward the NPC
    x = gr.plan_errand(err.house, err, "exit", {"map": 8, "x": 1, "y": 2, "dir": 0})
    assert x["steps"][-1]["warp"] and x["steps"][-1]["to"]["map"] == 7


def test_errand_refuses_a_wrong_start_map_and_a_bad_phase():
    outer, err = _errand()
    with pytest.raises(gr.RouteError) as e:
        gr.plan_errand(outer, err, "enter", {"map": 8, "x": 1, "y": 1, "dir": 0})
    assert e.value.reason == "map_mismatch"
    with pytest.raises(gr.RouteError) as e:
        gr.plan_errand(outer, err, "dance", _start(1, 1))
    assert e.value.reason == "unknown_phase"


# --- per-game save Location (pack-derived) ---------------------------------------------------------
class _FakeSave:
    def __init__(self, general):
        self.general = general


def _fake_general(game, loc):
    off = gr.location_spec(game)["general_off"]
    g = bytearray(0x40000)
    struct.pack_into("<5i", g, off, *loc)
    return bytes(g)


def test_location_offset_comes_from_the_pack_per_game():
    assert gr.location_spec("HG")["general_off"] == 0x1234  # the old hard-coded constant
    assert gr.location_spec("hge")["general_off"] == 0x1424  # hge's earlier arrays are larger
    assert gr.location_spec("hge")["array_id"] == 5
    with pytest.raises(gr.RouteError) as e:
        gr.location_spec("pt")
    assert e.value.reason == "unknown_game"


@pytest.mark.parametrize("game", ["HG", "hge"])
def test_save_position_reads_the_game_pack_offset(game, tmp_path, monkeypatch):
    sav = tmp_path / "x.SaveRAM"
    sav.write_bytes(b"x")
    g = _fake_general(game, (7, -1, 1, 1, 1))
    monkeypatch.setattr(gr, "parse_save", lambda _b, _p: _FakeSave(g))
    pos = gr.save_position(sav, game)
    assert pos == {"map": 7, "warp": -1, "x": 1, "y": 1, "dir": 1}
    r = gr.plan_route(_world(ROWS), pos, game=game)
    assert r["game"] == game


def test_a_wrong_pack_offset_is_refused(tmp_path, monkeypatch):
    sav = tmp_path / "x.SaveRAM"
    sav.write_bytes(b"x")
    g = _fake_general("hge", (7, -1, 1, 1, 1))
    monkeypatch.setattr(gr, "parse_save", lambda _b, _p: _FakeSave(g))
    good = gr.location_spec("hge")
    for bad in (good["general_off"] + 4, good["general_off"] - 0x1424 + 0x1234):
        monkeypatch.setattr(gr, "location_spec", lambda _g, bad=bad: {**good, "general_off": bad})
        pos = gr.save_position(sav, "hge")
        with pytest.raises(gr.RouteError) as e:  # a shifted read is not a real Location
            gr.plan_route(_world(ROWS), pos)
        assert e.value.reason == "map_mismatch"


# --- real data (named skips) ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def real():
    for p, what in ((ROM, "HG ROM"), (PRET, "pokeheartgold source"), (SAVE, "HG battery save")):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    return gr.load_world(ROM, PRET), gr.save_position(SAVE)


def test_real_save_position_is_new_bark_outside_the_player_house(real):
    world, pos = real
    assert (pos["map"], pos["x"], pos["y"]) == (60, 695, 397)
    assert world.map_at(pos["x"], pos["y"]) == pos["map"]  # matrix agrees with the save
    assert world.names[60] == "T20" and world.names[33] == "R29"


def test_real_route_is_walkable_ends_in_route29_grass_and_matches_the_door_check(real):
    world, pos = real
    # derivation check: every New Bark warp tile decodes to a door behaviour (0x69..0x6f)
    for x, y in ((684, 393), (695, 396), (679, 405), (690, 407)):
        assert 0x68 <= world.attr(x, y) & 0xFF <= 0x6F
    r = gr.plan_route(world, pos)
    _check_never_blocked(world, r)
    end = gr.replay(world, r)[-1]
    assert world.is_grass(*end) and world.map_at(*end) == 33
    assert r["map_name"] == "R29" and not r["water_tiles"]
    # the declared map ids on each segment end are the matrix's
    for s in r["steps"]:
        assert world.map_at(s["to"]["x"], s["to"]["y"]) == s["to"]["map"]
    json.dumps(r)  # JSON-clean


def test_real_every_warp_tile_decodes_to_a_door(real):
    world, _ = real
    decoded = [(x, y, world.attr(x, y)) for x, y in world.warps if world.attr(x, y) is not None]
    bad = [(x, y, a & 0xFF) for x, y, a in decoded if (a & 0xFF) not in gr.DOOR_BAND]
    # The door band is the proof for the land-data layout: a warp tile is a door by
    # construction, so 0x14 + the u16 at +0x12, the row-major order and the matrix index are
    # all pinned at once here. A fixed 0x14 puts only 162 of the 313 warp entries (the used
    # banks list a few tiles twice) in the band; at 0x14+extra it is every one but one.
    assert len(decoded) >= 307, f"only {len(decoded)} distinct warp tiles in the used banks"
    assert len(decoded) - len(bad) >= 306, f"{len(decoded) - len(bad)}/{len(decoded)} are doors"
    assert [b for _, _, b in bad] == [62], f"the door-band outlier changed: {bad}"


def test_real_wrong_map_id_refused(real):
    world, pos = real
    with pytest.raises(gr.RouteError):
        gr.plan_route(world, {**pos, "map": 33})


# --- hge real data ---------------------------------------------------------------------------------
HGE_ROM, HGE_SAVE = gr.HGE_ROM, gr.HGE_SAVE


def test_real_hge_world_files_are_byte_identical_to_vanilla():
    """hge reuses the pret events because the matrix, land-data and zone-event NARCs are the same
    bytes in both ROMs (hge_data_delta.md section 3); a rebuilt hge that changes any needs its own
    event source."""
    import hashlib

    ndspy_rom = pytest.importorskip("ndspy.rom")
    for p, what in ((ROM, "HG ROM"), (HGE_ROM, "hge ROM")):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    a = ndspy_rom.NintendoDSRom.fromFile(str(ROM))
    b = ndspy_rom.NintendoDSRom.fromFile(str(HGE_ROM))
    for name in (gr.MATRIX_NARC, gr.LAND_NARC, "a/0/3/2"):
        assert (
            hashlib.sha1(a.getFileByName(name)).digest()
            == hashlib.sha1(b.getFileByName(name)).digest()
        ), f"{name} differs between HG and hge"


def test_real_hge_save_position_matches_the_pack_cross_check():
    if not Path(HGE_SAVE).exists():
        pytest.skip(f"hge save absent: {HGE_SAVE}")
    pos = gr.save_position(HGE_SAVE, "hge")
    # the pack's FILE cross-check: Location (60,-1,685,396,1) on this save
    assert (pos["map"], pos["warp"], pos["x"], pos["y"], pos["dir"]) == (60, -1, 685, 396, 1)


def test_real_pokegear_errand_data_matches_the_decomp():
    for p, what in ((HGE_ROM, "hge ROM"), (PRET, "pokeheartgold source")):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    e = gr.load_errand(HGE_ROM, PRET, "pokegear", 60)
    # zone_event 057_T20 warp -> player house 1F; 060_T20R0201 door warp and Mom (gsmama)
    assert (e.house_id, e.door_out, e.door_in, e.npc) == (63, (695, 396), (3, 10), (6, 7))
    assert e.house.map_at(3, 10) == 63 and e.house.attr(3, 10) is not None


# --- the Cherrygrove PC stop (G1 row i / the `pc` phase) -------------------------------------------
def _pc_stop():
    """An outdoor strip with a door at (4,3) and an interior with the PC at (4,1); the stand tile is
    south of the PC, the counter tiles beside it are collisions."""
    outer = _world(["#######", "#.....#", "#.....#", "#######"], blocked={(4, 3)})
    house = _world(
        ["#######", "#.....#", "#.....#", "#.....#", "#######"], blocked={(4, 1), (1, 3)}, header=8
    )
    return outer, gr.Errand(8, 7, house, (4, 3), (1, 3), (4, 1))


def test_pc_leg_ends_on_the_tile_south_of_the_pc_facing_it():
    _, err = _pc_stop()
    r = gr.plan_pc(err, {"map": 8, "x": 1, "y": 3, "dir": 0})
    end = gr.replay(err.house, r)[-1]
    assert end == (4, 2) and r["pc"] == {"x": 4, "y": 1, "stand": [4, 2], "face": "Up"}
    assert r["kind"] == "pc" and r["phase"] == "deposit"
    _check_never_blocked(err.house, r)
    # already standing there: an empty walk, not a refusal
    assert gr.plan_pc(err, {"map": 8, "x": 4, "y": 2, "dir": 3})["steps"] == []


def test_pc_leg_refuses_a_wrong_map_and_an_unreachable_stand_tile():
    _, err = _pc_stop()
    with pytest.raises(gr.RouteError) as e:
        gr.plan_pc(err, {"map": 7, "x": 1, "y": 3, "dir": 0})
    assert e.value.reason == "map_mismatch"
    err.house.blocked.add((4, 2))  # a counter/NPC on the stand tile: the PC cannot be faced
    with pytest.raises(gr.RouteError) as e:
        gr.plan_pc(err, {"map": 8, "x": 1, "y": 3, "dir": 0})
    assert e.value.reason == "pc_data"


def test_the_walk_to_the_door_avoids_grass_when_a_detour_exists():
    # row 1 is 6 grass tiles; the clean detour along row 3 is a few tiles longer: grass is priced
    rows = [
        "###########",
        "#.gggggg..#",
        "#.#######.#",
        "#.........#",
        "###########",
    ]
    outer = _world(rows, blocked={(9, 1)})
    house = _world(["###", "#.#", "###"], header=8)
    err = gr.Errand(8, 7, house, (9, 1), (1, 1), (1, 1))
    r = gr.plan_errand(outer, err, "enter", _start(1, 1))
    body = {**r, "steps": r["steps"][:-1]}
    assert r["approach_grass"] == [] and not any(outer.is_grass(*t) for t in gr.replay(outer, body))
    assert gr.replay(outer, body)[-1] == (9, 2) and r["steps"][-1]["warp"]


def test_unavoidable_grass_and_coord_events_are_reported_to_the_walker():
    # the only way to the door crosses 2 grass tiles and a coord event: the Lua polls the battle chain
    # on the grass tiles (route.approach_grass) and, with route.run_from_wild, escapes the fight
    outer = _world(
        ["########", "#.gg...#", "########"],
        blocked={(6, 1)},
        soft={(4, 1)},
        scripts={(4, 1): ("T21_001",)},
    )
    house = _world(["###", "#.#", "###"], header=8)
    err = gr.Errand(8, 7, house, (6, 1), (1, 1), (1, 1))
    r = gr.plan_errand(outer, err, "enter", _start(1, 1))
    assert r["approach_grass"] == [[2, 1], [3, 1]]
    assert r["soft_events"] == [{"x": 4, "y": 1, "scriptIds": ["T21_001"]}]
    assert r["steps"][-1]["warp"] and r["steps"][-1]["to"]["map"] == 8


# --- pack-derived legs, RAM layout and the SYNTH setup --------------------------------------------
@pytest.mark.parametrize("game", ["HG", "hge"])
def test_pack_legs_resolve_the_battle_escape_and_the_native_save(game):
    legs = gr.pack_legs(game, gr.PC_LEGS + gr.SAVE_LEGS)
    run = legs["run_from_wild"]
    assert run["until"]["address"] == 0x021D4158 and run["until"]["symbol"] == "sFieldSysPtr"
    assert run["steps"][0]["press"] == ["X"]  # the first key press only wakes the battle cursor
    assert legs["start_menu_cursor_to_save"]["until"]["value"] == 5  # SAVE is cell 5
    assert [s["press"] for s in legs["start_menu_cursor_to_save"]["steps"]] == [["Down"], ["Left"]]
    assert legs["save_confirm_until_saved"]["until"]["value"] == 15  # TouchSaveApp CLOSE


def test_an_open_pack_leg_is_refused_by_name():
    with pytest.raises(gr.RouteError) as e:
        gr.pack_legs("HG", ["pc_open_storage"])
    assert e.value.reason == "leg_open" and "pc_open_storage" in str(e.value)


def test_pack_ram_comes_from_the_pack_and_hge_has_no_modified_word():
    hg, hge = gr.pack_ram("HG"), gr.pack_ram("hge")
    assert (hg["pc"]["cur_box_off"], hg["pc"]["mod_off"], hg["pc"]["boxes"]) == (
        0x12000,
        0x12004,
        18,
    )
    assert (hge["pc"]["cur_box_off"], hge["pc"]["mod_off"], hge["pc"]["boxes"]) == (None, 0x1E004, 30)
    assert hg["hdr_off"] == 143380 and hge["hdr_off"] == 192532  # hge's SaveData is larger
    assert (hg["id_party"], hg["id_pc"], hg["party"]["size"], hg["pc"]["mon_stride"]) == (
        2,
        41,
        236,
        136,
    )
    assert hg["field"]["save_state"] == 1 and hg["fieldsys"] == 0x021D4158


def _synth_save(tmp_path, *, sidecar=True, sha=None):
    save = tmp_path / "party2.SaveRAM"
    save.write_bytes(b"synthetic save bytes")
    if sidecar:
        row = {
            "schema": gr.SYNTH_SCHEMA,
            "kind": "party2",
            "out_sha1": sha or gr.sha1_of(save),
            "new_pid": 0xCAFEBABE,
            "otid": 0x12345678,
        }
        Path(str(save) + ".synth.json").write_text(json.dumps(row), encoding="utf-8")
    return save


def test_the_pc_run_refuses_a_save_without_its_synth_sidecar(tmp_path):
    save = _synth_save(tmp_path, sidecar=False)
    with pytest.raises(gr.RouteError) as e:
        gr.synth_setup(save)
    assert e.value.reason == "setup_missing" and "gen4_synth_save.py party2" in str(e.value)
    # the refusal comes before the lane is touched or the emulator is looked for
    with pytest.raises(gr.RouteError) as e:
        gr.run_lane(save=save, target="pc", lane="never_created_pc_lane")
    assert e.value.reason == "setup_missing"
    assert not gr.lane_dir("never_created_pc_lane").exists()


def test_the_synth_sidecar_must_describe_this_save(tmp_path):
    save = _synth_save(tmp_path, sha="0" * 40)
    with pytest.raises(gr.RouteError) as e:
        gr.synth_setup(save)
    assert e.value.reason == "setup_mismatch"
    with pytest.raises(gr.RouteError) as e:
        gr.run_lane(target="nowhere")
    assert e.value.reason == "unknown_target"


def test_the_receipt_is_labelled_synth_with_the_sidecar_hash(tmp_path):
    import hashlib

    save = _synth_save(tmp_path)
    synth = gr.synth_setup(save)
    sidecar = Path(str(save) + ".synth.json")
    assert synth["setup"] == "SYNTH" and synth["new_pid"] == 0xCAFEBABE
    assert synth["sidecar_sha256"] == hashlib.sha256(sidecar.read_bytes()).hexdigest()
    legs = [
        {
            "leg": 1,
            "kind": "pc",
            "phase": "deposit",
            "status": "PC_DEPOSIT",
            "detail": "x",
            "log": "y",
        }
    ]
    rec = gr.build_receipt("HG", save, synth, legs, {"status": "PC_DEPOSIT", "detail": "x"})
    assert (rec["setup"], rec["sidecar_sha256"], rec["final_status"]) == (
        "SYNTH",
        synth["sidecar_sha256"],
        "PC_DEPOSIT",
    )
    assert "log" not in rec["legs"][0]  # only the status line travels


def test_resync_detail_carries_done_and_old_logs_still_parse():
    new = gr.RESYNC_RE.search("map=69 x=8 y=19 dir=0 done=1 state=C:/a.State")
    assert (new[1], new[5], new[6]) == ("69", "1", "C:/a.State")
    mid = gr.RESYNC_RE.search("map=33 x=1 y=2 dir=2 done=0 state=C:/b.State")
    assert mid[5] == "0"  # interrupted mid-walk: the same phase is re-planned
    old = gr.RESYNC_RE.search("map=60 x=1 y=2 dir=1 state=C:/c.State")
    assert old[5] is None and old[6] == "C:/c.State"


def test_the_lua_leg_reads_only_keys_the_planner_and_pack_provide():
    src = (gr.REPO / "lua/tests/gen4_route_play.lua").read_text(encoding="utf-8")
    ram = gr.pack_ram("HG")

    for k in set(re.findall(r"\bRAM\.(\w+)", src)):
        assert k in ram, f"Lua reads RAM.{k}, which pack_ram does not provide"
    for k in set(re.findall(r"\bF\.(\w+)", src)):
        assert k in ram["field"], f"Lua reads F.{k}, absent from probe_field"
    assert set(
        re.findall(
            r'"(open_start_menu|start_menu_\w+|save_confirm_until_saved|close_start_menu)"', src
        )
    ) == set(gr.SAVE_LEGS)
    for k in ("run_from_wild", "persistence", "ram", "synth", "pc"):
        assert f"route.{k}" in src


def test_the_pc_behaviour_and_facing_requirement_match_the_decomp():
    for p, what in ((PRET, "pokeheartgold source"),):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    mb = (PRET / "include/constants/metatile_behavior.h").read_text(encoding="utf-8")
    body = mb[mb.index("enum TILE_BEHAVIOR {") :]
    names = re.findall(r"TILE_BEHAVIOR_\w+", body.split("};")[0])
    assert names.index("TILE_BEHAVIOR_131") == gr.PC_BEHAVIOR == 0x83  # enum position = value
    c = (PRET / "src/metatile_behavior.c").read_text(encoding="utf-8")
    assert re.search(r"BOOL sub_0205B7E0\(u8 tile\) \{\s*return tile == TILE_BEHAVIOR_131;", c)
    asm = (PRET / "asm/overlay_01_021E6880.s").read_text(encoding="utf-8")
    # GetInteractedMetatileScript: PC script only when the player faces north (r6 == 0)
    pc = asm[asm.index("bl sub_0205B7E0") :][:400]
    assert "cmp r6, #0" in pc and "std_pokecenter_pc" in pc
    std = (PRET / "include/constants/std_script.h").read_text(encoding="utf-8")
    assert re.search(r"#define std_pokecenter_pc\s+2010", std)


def test_real_cherrygrove_pc_data_matches_the_decomp():
    for p, what in ((ROM, "HG ROM"), (PRET, "pokeheartgold source")):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    e = gr.load_errand(ROM, PRET, "cherrygrove_pc", gr.CHERRYGROVE_ID)
    # zone_event 064_T21 warp -> MAP_CHERRYGROVE_POKECENTER_1F; 066_T21PC0101 door warp; the PC tile
    assert (e.house_id, e.door_out, e.door_in, e.npc) == (69, (564, 391), (8, 19), (11, 12))
    assert e.house.map_at(8, 19) == 69  # the interior loads as its own map
    assert e.house.attr(8, 19) is not None and e.house.attr(11, 12) & 0x8000  # PC tile is solid
    stand = (e.npc[0], e.npc[1] + 1)
    assert e.house.walkable(*stand)
    # the interior bg event at (4,8) is not the PC (it decodes to behaviour 0x85)
    assert (e.house.attr(4, 8) & 0xFF) == 0x85 and (4, 8) in e.house.blocked


def test_real_pc_stop_plan_from_the_hg_save(real):
    world, pos = real
    plan = gr.plan_pc_stop(ROM, PRET, world, pos)
    enter, dep = plan["enter"], plan["deposit"]
    # outdoors: never crosses a blocked tile, ends in front of the door and takes the warp into map 69
    body = {**enter, "steps": enter["steps"][:-1]}
    _check_never_blocked(world, body)
    assert gr.replay(world, body)[-1] == (564, 392)
    assert enter["steps"][-1]["warp"] and enter["steps"][-1]["to"]["map"] == 69
    maps = {s["to"]["map"] for s in enter["steps"][:-1]}
    assert maps == {33, 67}  # Route 29 and Cherrygrove (the New Bark start tile is map 60)
    # encounters: the corridor has grass no path avoids; every tile is named for the battle poll
    assert 0 < len(enter["approach_grass"]) <= 40
    assert all(world.is_grass(*t) for t in map(tuple, enter["approach_grass"]))
    ids = {sid for e in enter["soft_events"] for sid in e["scriptIds"]}
    assert ids == {
        "_EV_scr_seq_T20_002 + 1",
        "_EV_scr_seq_R29_001 + 1",
        "_EV_scr_seq_T21_003 + 1",
        "_EV_scr_seq_T21_001 + 1",
    }
    # indoors: ends on the tile south of the PC, facing it
    pc = gr.load_errand(ROM, PRET, "cherrygrove_pc", gr.CHERRYGROVE_ID)
    _check_never_blocked(pc.house, dep)
    assert gr.replay(pc.house, dep)[-1] == (11, 13) and dep["pc"]["face"] == "Up"
    assert (pc.house.attr(11, 12) & 0xFF) == gr.PC_BEHAVIOR  # the tile north of it is the PC
    json.dumps(plan)


def test_real_pc_stop_plan_wrong_map_is_refused(real):
    world, pos = real
    with pytest.raises(gr.RouteError) as e:
        gr.plan_pc_stop(ROM, PRET, world, {**pos, "map": 33})
    assert e.value.reason == "map_mismatch"


# --- the Lua PC leg against a fake DS (lupa): Lua plumbing, NOT game truth --------------------------
# The fake encodes the control flow documented in lua/tests/gen4_route_play.lua (PC script menus, the
# OVY_14 state machine, the start-menu SAVE panel). It proves the leg's loops, RAM readers and
# verifications run end to end and fail by name; whether the real game behaves like the fake is the
# live run's job (card gen4-C1-10 phase 2).
class _Exit(Exception):
    pass


class FakeDS:
    BASE = 0x02000000
    FS, SUB0, LOC, DRV, DATA, P3, P4 = (
        0x02300000,
        0x02301000,
        0x02302000,
        0x02303000,
        0x02303100,
        0x02303200,
        0x02303300,
    )
    MAN, APPD, SAVE = 0x02304000, 0x02305000, 0x02310000
    AV, MO = 0x02304800, 0x02304900
    PARTY_OFF, PC_OFF = 0x90, 0x10000

    def __init__(self, ram_layout, stand, new_pid, *, wake_first=False, party=2):
        self.ram = bytearray(0x400000)
        self.R = ram_layout
        self.stand, self.new_pid, self.wake_first = stand, new_pid, wake_first
        self.frame, self.prev, self.t, self.exited = 0, set(), 0, False
        self.x, self.y, self.dir = stand[0], stand[1], 3  # facing east after the walk
        self.mode, self.sub, self.cursor, self.toolbar, self.woke = "field", "", 0, False, False
        w = self.w32
        w(0x021D4158, self.FS)
        w(0x021D2228, self.SAVE)
        w(self.FS, self.SUB0)
        w(self.FS + 0x6C, 1)
        w(self.FS + 0x20, self.LOC)
        w(self.FS + 0x40, self.AV)  # PlayerAvatar -> LocalMapObject -> currentFacing
        w(self.AV + 0x30, self.MO)
        w(self.FS + 216, self.DRV)
        w(self.DRV + 16, self.DATA)
        w(self.DATA + 4, self.P3)
        w(self.P3 + 16, self.P4)
        self.ram[self.DATA - self.BASE + 1] = 1  # save driver idle
        R = ram_layout
        for aid, off in ((R["id_party"], self.PARTY_OFF), (R["id_pc"], self.PC_OFF)):
            h = self.SAVE + R["hdr_off"] + aid * R["hdr_size"]
            w(h, aid)
            w(h + R["hdr_offset_field"], off)
        self.party = self.SAVE + R["dyn_off"] + self.PARTY_OFF
        self.pc = self.SAVE + R["dyn_off"] + self.PC_OFF
        w(self.party, 6)
        w(self.party + R["party"]["count_off"], party)
        for i, pid in enumerate((0x1111, new_pid)[:party]):
            w(self.party + R["party"]["mons_off"] + i * R["party"]["size"], pid)
        self.sync()

    # --- memory
    def w32(self, a, v):
        struct.pack_into("<I", self.ram, a - self.BASE, v & 0xFFFFFFFF)

    def r(self, a, n):
        o = a - self.BASE
        return int.from_bytes(self.ram[o : o + n], "little") if 0 <= o < len(self.ram) - 4 else 0

    def sync(self):
        # Location.direction is NOT the live facing (it stays 0): the leg must read the map object
        struct.pack_into("<5i", self.ram, self.LOC - self.BASE, 8, -1, self.x, self.y, 0)
        self.w32(self.MO + 0x28, self.dir)

    def task(self, v):
        self.w32(self.FS + 16, v)

    def app_state(self, s):
        self.st, self.t = s, 0
        self.w32(self.MAN + 0x14, s)

    # --- the game
    def step(self, held):
        if self.exited:
            raise _Exit
        self.frame += 1
        new = {b for b in held if b not in self.prev}
        self.prev, self.t = set(held), self.t + 1
        getattr(self, "_" + self.mode)(held, new)
        self.sync()

    def _field(self, held, new):
        if "Up" in held and self.dir != 0:
            self.dir = 0
        if "A" in new and (self.x, self.y) == tuple(self.stand) and self.dir == 0:
            self.mode, self.sub, self.t = "script", "msg1", 0
            self.task(1)
        if "X" in new:
            self.mode, self.t, self.cell, self.panel = "startmenu", 0, 0, 0
            self.task(1)
            self.panel_sync()

    def _script(self, held, new):
        order = ["msg1", "menu_pc", "msg2", "menu_sub"]
        if self.t < 8:
            return
        if "A" in new and self.sub in order[:3]:
            self.sub, self.t = order[order.index(self.sub) + 1], 0
        elif "A" in new and self.sub == "menu_sub":  # DEPOSIT POKEMON -> the PC application
            self.mode, self.t = "launching", 0
        elif "B" in new and self.sub == "menu_sub":
            self.sub, self.t = "menu_pc2", 0
        elif "B" in new and self.sub == "menu_pc2":
            self.mode = "field"
            self.task(0)

    def _launching(self, held, new):
        if self.t >= 20:
            self.w32(self.SUB0 + 4, self.MAN)
            self.w32(self.MAN + 0x0C, 14)
            self.w32(self.MAN + 0x1C, self.APPD)
            self.ram[self.APPD - self.BASE + 0x21] = 0xFF
            self.mode, self.cursor, self.toolbar = "app", 0, False
            self.app_state(0xB)

    def _app(self, held, new):
        st, t = self.st, self.t
        if st == 0xB and t >= 30:
            self.app_state(0x5B)
        elif st == 0x5B and t >= 10:
            if "Right" in new:
                if self.wake_first and not self.woke:
                    self.woke = True  # the first d-pad press only wakes the cursor
                else:
                    self.cursor = min(self.cursor + 1, 1)
            if "A" in new:
                if self.toolbar:
                    self.app_state(0x5C)
                elif self.cursor < self.r(self.party + self.R["party"]["count_off"], 4):
                    self.toolbar = True
                    self.ram[self.APPD - self.BASE + 0x21] = 0x1E + self.cursor
                    self.app_state(0x6F)
            elif "B" in new:
                if self.toolbar:
                    self.toolbar = False
                    self.app_state(0x70)
                else:
                    self.app_state(0x94)
        elif st in (0x6F, 0x70) and t >= 20:
            self.app_state(0x5B)
        elif st == 0x94 and t >= 10:
            self.app_state(7)
        elif st == 7 and "B" in new:
            self.app_state(0xB3)
        elif st == 0xB3 and t >= 30:
            self.w32(self.SUB0 + 4, 0)
            self.mode, self.sub, self.t = "script", "menu_sub", 0
        elif st == 0x5C and t >= 40:
            self.app_state(0x61)
        elif st == 0x61 and t >= 10 and "A" in new:
            self.app_state(0x66)
        elif st == 0x66 and t >= 60:
            self.commit()
            self.app_state(0x6B)
        elif st == 0x6B and t >= 40:
            self.toolbar = False
            self.app_state(0x5B)

    def commit(self):
        R = self.R
        slot = self.cursor
        pid = self.r(self.party + R["party"]["mons_off"] + slot * R["party"]["size"], 4)
        self.w32(self.pc + 0 * R["pc"]["box_stride"] + 0 * R["pc"]["mon_stride"], pid)
        self.w32(self.party + R["party"]["mons_off"] + slot * R["party"]["size"], 0)
        self.w32(self.party + R["party"]["count_off"], 1)
        if R["pc"]["mod_off"] is not None:
            self.w32(self.pc + R["pc"]["mod_off"], self.r(self.pc + R["pc"]["mod_off"], 4) | 1)

    def panel_sync(self):
        self.w32(self.P4 + 20, self.cell)
        self.w32(self.P4 + 12, self.panel)

    def _startmenu(self, held, new):
        if self.t < 10:
            return
        if self.panel == 0:
            if "Down" in new:
                self.cell = 2
            if "Left" in new and self.cell == 2:
                self.cell = 5
            if "A" in new and self.cell == 5:
                self.panel = 4
            if "B" in new:
                self.mode = "field"
                self.task(0)
        elif self.panel == 4 and "A" in new:
            self.panel, self.t = 15, 0
            mod = self.R["pc"]["mod_off"]
            if mod is not None:
                self.w32(self.pc + mod, 0)  # Save_ResetPCBoxModifiedFlags
        elif self.panel == 15 and self.t >= 30:
            self.panel = 0
        self.panel_sync()


def _run_lua_leg(tmp_path, monkeypatch, *, wake_first=False, party=2, pid=0xCAFEBABE):
    lupa = pytest.importorskip("lupa")
    _, err = _pc_stop()
    stand = (4, 2)
    route = gr.plan_pc(err, {"map": 8, "x": stand[0], "y": stand[1], "dir": 1})
    route.update(
        run_from_wild=gr.pack_legs("HG", gr.PC_LEGS)["run_from_wild"],
        persistence=gr.pack_legs("HG", gr.SAVE_LEGS),
        ram=gr.pack_ram("HG"),
        synth={"new_pid": pid, "otid": 0x12345678},
    )
    rpath, out = tmp_path / "route.json", tmp_path / "out.log"
    rpath.write_text(json.dumps(route), encoding="utf-8")
    env = {
        "G4_REPO": str(gr.REPO).replace("\\", "/"),
        "G4_ROUTE": str(rpath).replace("\\", "/"),
        "G4_OUT": str(out).replace("\\", "/"),
        "G4_LANE": str(tmp_path).replace("\\", "/"),
        "G4_TAG": "t",
        "G4_LOAD_STATE": "",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    ds = FakeDS(route["ram"], stand, pid, wake_first=wake_first, party=party)
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    held: dict = {}

    def frameadvance():
        h = set(held)
        held.clear()
        ds.step(h)

    def joypad_set(t):
        held.clear()
        held.update({k: True for k, v in t.items() if v})

    def read(n):
        return lambda a, _d=None: ds.r(a, n)

    def noop(*_a):
        return None

    def exit_():
        ds.exited = True

    g = lua.globals()
    g.emu = lua.table(frameadvance=frameadvance, framecount=lambda: ds.frame, limitframerate=noop)
    g.joypad = lua.table(set=joypad_set)
    g.memory = lua.table(read_u32_le=read(4), read_u16_le=read(2), read_u8=read(1))
    g.savestate = lua.table(save=noop, load=noop)
    g.client = lua.table(screenshot=noop, exit=exit_)
    src = (gr.REPO / "lua/tests/gen4_route_play.lua").read_text(encoding="utf-8")
    try:
        lua.execute(src)
    except Exception as exc:  # the script ends in finish(): the fake raises once client.exit ran
        assert ds.exited, f"the Lua leg crashed instead of finishing: {exc}"
    last = [ln for ln in out.read_text(encoding="utf-8").splitlines() if "RESULT" in ln][-1]
    return last, ds, out.read_text(encoding="utf-8")


def test_the_lua_pc_leg_deposits_saves_and_verifies_against_a_fake_ds(tmp_path, monkeypatch):
    last, ds, log = _run_lua_leg(tmp_path, monkeypatch)
    assert (
        "RESULT PC_DEPOSIT party=2->1 box=0/0 pid=0xcafebabe modified=0x1->0 save_driver=idle"
        in last
    ), log
    assert ds.r(ds.party + ds.R["party"]["count_off"], 4) == 1
    assert (
        "slot 1" not in log and "select try 1 sel 0x1f" in log
    )  # the cursor selected slot 1 first try


def test_the_lua_pc_leg_retries_a_cursor_that_only_woke_up(tmp_path, monkeypatch):
    last, _, log = _run_lua_leg(tmp_path, monkeypatch, wake_first=True)
    # first Right is swallowed: slot 0 is selected, cancelled with B, then Right+A picks slot 1
    assert "select try 1 sel 0x1e" in log and "select try 2 sel 0x1f" in log
    assert "RESULT PC_DEPOSIT" in last, log


def test_the_lua_pc_leg_refuses_a_save_that_is_not_the_synth_setup(tmp_path, monkeypatch):
    last, _, _ = _run_lua_leg(tmp_path, monkeypatch, party=1)
    assert "RESULT FAIL setup_not_party2" in last
    last, _, _ = _run_lua_leg(tmp_path, monkeypatch, pid=0xCAFEBABE)  # control: the setup passes
    assert "RESULT PC_DEPOSIT" in last


# --- run_lane phase sequencing (fake emulator process, real map data) -----------------------------
_SYNTH = {
    "setup": "SYNTH",
    "sidecar": "party2.SaveRAM.synth.json",
    "sidecar_sha256": "ab" * 32,
    "new_pid": 0xABCD1234,
    "otid": 0x00010002,
    "out_sha1": "x",
    "kind": "party2",
    "species": None,
}


def _fake_emuhawk(monkeypatch, tmp_path, pos, script):
    """Replace the EmuHawk process and the fixtures it needs: `script(leg, route)` returns the leg's
    log text. Returns the recorded (route, load_state) of every launched leg."""
    calls = []
    witnesses = iter(({"bank": 0, "counter": 1, "keys": ["K"]}, {"bank": 1, "counter": 2, "keys": ["K"]}, {"bank": 1, "counter": 2, "keys": ["K"]}))
    monkeypatch.setattr(gr, "save_witness", lambda *a: next(witnesses))

    class FakeProc:
        def __init__(self, cmd, cwd=None, env=None):
            route = json.loads(Path(env["G4_ROUTE"]).read_text(encoding="utf-8"))
            calls.append({"route": route, "load_state": env["G4_LOAD_STATE"]})
            Path(env["G4_OUT"]).write_text(script(len(calls), route), encoding="utf-8")

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    for name, fake in {
        "lane_dir": lambda lane: tmp_path / lane,
        "write_nds_run_config": lambda *a, **k: None,
        "kill_our_emuhawk": lambda *a, **k: None,
        "stage_rom": lambda rom, ld: Path(ld) / "rom.nds",
        "stage_save": lambda save, ld, *a, **k: Path(ld) / "x.SaveRAM",
        "sha1_of": lambda p: "0" * 40,
        "synth_setup": lambda save, kind="party2": _SYNTH,
        "save_position": lambda save, game="HG": pos,
        "verify_saved": lambda *a: {"party": 1, "box": 0, "slot": 0},
        "git_head": lambda: "f" * 40,  # git itself runs through the faked Popen
    }.items():
        monkeypatch.setattr(gr, name, fake)
    monkeypatch.setattr(gr.subprocess, "Popen", FakeProc)
    return calls


def test_run_lane_replans_an_interrupted_enter_leg_then_deposits(real, tmp_path, monkeypatch):
    _, pos = real

    def script(leg, route):
        if leg == 1:  # a coord-event cutscene mid-walk (done=0): the same phase must be re-planned
            assert (
                route["kind"] == "errand" and route["phase"] == "enter" and route["run_from_wild"]
            )
            return "[f1] RESULT RESYNC map=33 x=640 y=398 dir=2 done=0 state=C:/s1.State\n"
        if leg == 2:  # re-planned from the logged tile, resumed from the state, reaches the door
            assert route["start"]["x"] == 640 and route["phase"] == "enter"
            return "[f2] RESULT RESYNC map=69 x=8 y=19 dir=0 done=1 state=C:/s2.State\n"
        if route["kind"] == "reload":  # the cold reload boots the saved battery fresh
            assert (
                leg == 4 and not route["steps"] and route["synth"]["new_pid"] == _SYNTH["new_pid"]
            )
            return "[f4] RESULT RELOAD_OK party=1 box=0/0\n"
        assert route["kind"] == "pc" and route["start"]["map"] == 69
        assert route["synth"]["new_pid"] == _SYNTH["new_pid"] and route["persistence"]
        assert route["ram"]["id_pc"] == 41
        return "[f3] RESULT PC_DEPOSIT party=2->1 box=0/0\n"

    calls = _fake_emuhawk(monkeypatch, tmp_path, pos, script)
    save = tmp_path / "party2.SaveRAM"
    res = gr.run_lane(ROM, save, PRET, target="pc", lane="L", tag="t")
    assert res["status"] == "PC_DEPOSIT"
    assert [c["load_state"] for c in calls] == [
        "",
        "C:/s1.State",
        "C:/s2.State",
        "",
    ]  # the cold reload boots fresh
    rec = json.loads((tmp_path / "L" / "t_receipt.json").read_text(encoding="utf-8"))
    assert rec["setup"] == "SYNTH" and rec["sidecar_sha256"] == _SYNTH["sidecar_sha256"]
    assert [leg["status"] for leg in rec["legs"]] == ["RESYNC", "RESYNC", "PC_DEPOSIT", "RELOAD_OK"]


def test_run_lane_stops_a_cutscene_that_puts_the_player_back(real, tmp_path, monkeypatch):
    _, pos = real
    here = f"map={pos['map']} x={pos['x']} y={pos['y']} dir=1 done=0 state=C:/s.State"
    _fake_emuhawk(monkeypatch, tmp_path, pos, lambda leg, route: f"[f1] RESULT RESYNC {here}\n")
    res = gr.run_lane(ROM, tmp_path / "party2.SaveRAM", PRET, target="pc", lane="L", tag="t")
    assert res["status"] == "RESYNC_LOOP"  # the same script again: no endless re-planning


def test_run_lane_reports_a_saved_file_that_lacks_the_clone(real, tmp_path, monkeypatch):
    _, pos = real
    calls = _fake_emuhawk(
        monkeypatch, tmp_path, pos, lambda leg, route: "[f1] RESULT PC_DEPOSIT x\n"
    )

    def refuse(*a):
        raise gr.RouteError("saved_mismatch", "saved file: party 2 mons")

    monkeypatch.setattr(gr, "verify_saved", refuse)
    res = gr.run_lane(ROM, tmp_path / "party2.SaveRAM", PRET, target="pc", lane="L", tag="t")
    assert (
        res["status"] == "SAVE_MISMATCH" and "saved_mismatch" in res["detail"] and len(calls) == 1
    )


# --- SoulSilver (same HGSS pack, title "soulsilver") ---------------------------------------------
SS_ROM, SS_SAVE = gr.SS_ROM, gr.SS_SAVE


def test_ss_uses_the_hgss_pack_title_and_the_same_location_offset():
    assert gr.GAMES["SS"][1:] == ("soulsilver", "hgss")
    assert gr.location_spec("SS")["general_off"] == 0x1234
    assert gr.pack_ram("SS") == gr.pack_ram("HG")  # same symbols, same save geometry
    assert gr.pack_legs("SS", gr.SAVE_LEGS) == gr.pack_legs("HG", gr.SAVE_LEGS)


def test_real_ss_world_files_are_byte_identical_to_vanilla_hg():
    import hashlib

    ndspy_rom = pytest.importorskip("ndspy.rom")
    for p, what in ((ROM, "HG ROM"), (SS_ROM, "SS ROM")):
        if not Path(p).exists():
            pytest.skip(f"{what} absent: {p}")
    a = ndspy_rom.NintendoDSRom.fromFile(str(ROM))
    b = ndspy_rom.NintendoDSRom.fromFile(str(SS_ROM))
    for name in (gr.MATRIX_NARC, gr.LAND_NARC, "a/0/3/2"):
        assert (
            hashlib.sha1(a.getFileByName(name)).digest()
            == hashlib.sha1(b.getFileByName(name)).digest()
        ), f"{name} differs between HG and SS"


def test_real_ss_save_position_is_new_bark():
    if not Path(SS_SAVE).exists():
        pytest.skip(f"SS save absent: {SS_SAVE}")
    pos = gr.save_position(SS_SAVE, "SS")
    assert (pos["map"], pos["x"], pos["y"]) == (60, 687, 397)


# --- verify_saved: the exact claim (clone at box 0 slot 0, party 1, cur_box 0), battery flag recorded ---
class _FakeBattery:
    def __init__(self, *, party=1, boxes=None, meta=None):
        self._party, self._meta = (
            [{}] * party,
            meta or {"box_count": 18, "cur_box": 0, "modified": 1},
        )
        self._boxes = boxes if boxes is not None else {(0, 0): "AAAA0001:BBBB0002"}

    def party(self):
        return self._party

    def boxes(self):
        out = [{"mons": {}} for _ in range(18)]
        for (b, s), key in self._boxes.items():
            out[b]["mons"][s] = {"key": key}
        return out

    def pc_meta(self):
        return self._meta


def _verify(monkeypatch, tmp_path, **kw):
    f = tmp_path / "b.SaveRAM"
    f.write_bytes(b"x")
    monkeypatch.setattr(gr, "parse_save", lambda _b, _p: _FakeBattery(**kw))
    return gr.verify_saved(f, "HG", {"new_pid": 0xAAAA0001, "otid": 0xBBBB0002})


def test_verify_saved_asserts_box0_slot0_party1_cur_box0_and_records_the_battery_flag(
    monkeypatch, tmp_path
):
    ok = _verify(monkeypatch, tmp_path)
    assert (ok["party"], ok["box"], ok["slot"], ok["cur_box"], ok["battery_modified"]) == (
        1,
        0,
        0,
        0,
        1,
    )
    for bad in (
        {"boxes": {(0, 1): "AAAA0001:BBBB0002"}},  # wrong slot
        {"boxes": {(1, 0): "AAAA0001:BBBB0002"}},  # wrong box
        {"boxes": {}},  # clone not boxed
        {"party": 2},  # still two party mons
        {"meta": {"box_count": 18, "cur_box": 3, "modified": 1}},  # active box moved
        {"boxes": {(0, 0): "AAAA0001:BBBB0002", (2, 5): "AAAA0001:BBBB0002"}},  # boxed twice
    ):
        with pytest.raises(gr.RouteError) as e:
            _verify(monkeypatch, tmp_path, **bad)
        assert e.value.reason == "saved_mismatch", bad


def test_the_receipt_carries_the_battery_the_reload_leg_and_the_ram_vs_file_flag_split():
    synth = {"setup": "SYNTH", "sidecar": "s", "sidecar_sha256": "0", "out_sha1": "x"}
    final = {
        "status": "PC_DEPOSIT",
        "detail": "d",
        "battery_sha1": "ab" * 20,
        "saved": {"clone_key": "K", "box": 0, "slot": 0, "battery_modified": 1},
        "reload": {
            "leg": 5,
            "status": "RELOAD_OK",
            "detail": "party=1",
            "wall": 9.9,
            "log": "L",
            "lines": ["x"],
        },
    }
    rec = gr.build_receipt("HG", "s.SaveRAM", synth, [], final)
    assert rec["battery_sha1"] == "ab" * 20 and rec["battery"]["slot"] == 0
    assert rec["reload"] == {
        "leg": 5,
        "status": "RELOAD_OK",
        "detail": "party=1",
        "wall": 9.9,
        "log": "L",
    }
    assert (
        rec["modified_flag"]["battery"] == 1
        and "0 after the native SAVE" in rec["modified_flag"]["ram"]
    )
    assert "clears" not in json.dumps(rec["modified_flag"])  # SAVE does not clear the file's word


# --- the egg-hatch pace (plan_hatch) ------------------------------------------------------------
def test_plan_hatch_paces_between_two_plain_tiles_and_skips_grass_coord_and_warp_neighbours():
    # west neighbour is grass, east is a coord-event tile, south is a warp: only north is plain floor
    w = _world(
        ["#####", "#...#", "#.g.#", "#...#", "#####"],
        soft={(3, 2)},
        warps=[(2, 3)],
        blocked={(2, 3)},
    )
    start = {"map": 7, "x": 2, "y": 1, "dir": 1}
    r = gr.plan_hatch(w, start)
    assert r["kind"] == "hatch" and r["pace"]["a"] == [2, 1]
    assert r["pace"]["b"] in ([1, 1], [3, 1]) and r["pace"]["dir_ab"] in ("Left", "Right")
    # a start on grass or a wrong map is refused by name
    with pytest.raises(gr.RouteError) as e:
        gr.plan_hatch(w, {"map": 7, "x": 2, "y": 2, "dir": 1})
    assert e.value.reason == "start_not_plain"
    with pytest.raises(gr.RouteError) as e:
        gr.plan_hatch(w, {**start, "map": 8})
    assert e.value.reason == "map_mismatch"
    boxed_in = _world(["###", "#.#", "###"])
    with pytest.raises(gr.RouteError) as e:
        gr.plan_hatch(boxed_in, {"map": 7, "x": 1, "y": 1, "dir": 1})
    assert e.value.reason == "no_pace_tile"


# --- receipts bound at consumption (verify_receipt) ------------------------------------------------
def test_counter_progress_rejects_no_save_or_old_reload_and_reverts():
    before = {"bank": 0, "counter": 1, "keys": ["K"]}
    after = {"bank": 1, "counter": 2, "keys": ["K"]}
    gr.assert_save_progress(before, after, after)
    for saved, reload in ((before, before), (after, before), (after, dict(after, keys=["other"]))):
        with pytest.raises(gr.RouteError):
            gr.assert_save_progress(before, saved, reload)
        gr.assert_save_progress(before, after, after)
    gr.assert_save_progress(dict(before, counter=0xFFFFFFFF), dict(after, counter=0), dict(after, counter=0))


HEAD = "a" * 40


def _route_doc(**over):
    from tools import gen4_pins

    doc = {
        **gr.receipt_binding(),
        "source_head": HEAD,
        "title": "heartgold",
        "rom_sha1": gen4_pins.ROM_SPECS["heartgold"][0],
        "final_status": "PC_DEPOSIT",
        "before_save": {"bank": 0, "counter": 1, "keys": ["K"]},
        "battery": {"bank": 1, "counter": 2, "keys": ["K"]},
        "reload": {"witness": {"bank": 1, "counter": 2, "keys": ["K"]}},
    }
    return {**doc, **over}


def _catch_doc(**over):
    from tools import gen4_pins

    doc = {
        **gr.receipt_binding(kind="catch", title="soulsilver"),
        "source_head": HEAD,
        "title": "soulsilver",
        "rom_sha1": gen4_pins.ROM_SPECS["soulsilver"][0],
        "verdict": "PASS",
        "battery_mon": {"key": "K", "pid": 1, "species": 16},
    }
    return {**doc, **over}


def _consume(tmp_path, doc, kind="route"):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return gr.verify_receipt(path, kind, head=HEAD)


def test_verify_receipt_passes_only_a_receipt_bound_to_this_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "git_head", lambda: HEAD)
    assert _consume(tmp_path, _route_doc())[0] == "PASS"  # baseline green before any fault
    assert _consume(tmp_path, _route_doc(final_status="HATCH_OK"))[0] == "PASS"
    assert _consume(tmp_path, _route_doc(final_status="RESYNC_LOOP"))[0] == "FAIL"
    assert _consume(tmp_path, _route_doc(final_status="OPEN"))[0] == "OPEN"
    assert _consume(tmp_path, _catch_doc(), "catch")[0] == "PASS"
    assert _consume(tmp_path, _catch_doc(verdict="FAIL"), "catch")[0] == "FAIL"


@pytest.mark.parametrize(
    "fault", ["script_hash", "module_hash", "no_modules"]
)
def test_verify_receipt_is_stale_never_pass(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(gr, "git_head", lambda: HEAD)
    assert _consume(tmp_path, _route_doc())[0] == "PASS"
    mods = dict(_route_doc()["module_sha256"])
    over = {
        "head": {"source_head": "b" * 40},
        "script_hash": {"script_sha256": "0" * 64},
        "module_hash": {"module_sha256": {**mods, "tools/gen4_routes.py": "0" * 64}},
        "unbound_head": {"source_head": ""},
        "no_modules": {"module_sha256": {}},
    }[fault]
    verdict, why = _consume(tmp_path, _route_doc(**over))
    assert verdict == "STALE", why


def test_a_missing_bound_file_is_stale(tmp_path):
    path = tmp_path / "r.json"
    mods = _route_doc()["module_sha256"]
    assert _consume(tmp_path, _route_doc())[0] == "PASS"
    doc = _route_doc(module_sha256={**mods, "lua/gen4/no_such_module.lua": "0" * 64})
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert gr.verify_receipt(path, "route", head=HEAD)[0] == "STALE"


def test_b1_a_trimmed_receipt_is_refused_for_each_required_module(tmp_path):
    """B1: module_sha256 must be a superset of the kind's required set; dropping any one hash is STALE."""
    assert _consume(tmp_path, _route_doc())[0] == "PASS"
    for kind, doc_fn in (("route", _route_doc), ("catch", _catch_doc)):
        full = doc_fn()
        assert _consume(tmp_path, full, kind)[0] == "PASS"
        for mod in gr.RECEIPT_KINDS[kind]["modules"]:
            trimmed = {k: v for k, v in full["module_sha256"].items() if k != mod}
            verdict, why = _consume(tmp_path, {**full, "module_sha256": trimmed}, kind)
            assert verdict == "STALE" and mod in why, (kind, mod, why)


def test_b2_the_script_must_be_the_kinds_script(tmp_path):
    """B2: a receipt hashing some OTHER (even unchanged) Lua script is not evidence for this kind."""
    assert _consume(tmp_path, _route_doc())[0] == "PASS"
    other = "lua/tests/probe_gen4_catch.lua"
    doc = _route_doc(script=other, script_sha256=gr._sha256(gr.REPO / other))
    verdict, why = _consume(tmp_path, doc)
    assert verdict == "STALE" and "script" in why
    assert (
        _consume(tmp_path, _catch_doc(script="lua/tests/gen4_route_play.lua"), "catch")[0]
        == "STALE"
    )


def test_b4_the_rom_is_bound_to_the_pinned_title_rom(tmp_path):
    """B4: rom_sha1 must equal the pinned ROM of the receipt's title; absent is unbound, wrong is FAIL."""
    from tools import gen4_pins

    assert _consume(tmp_path, _route_doc())[0] == "PASS"
    assert _consume(tmp_path, _route_doc(rom_sha1="0" * 40))[0] == "STALE"
    # the SS ROM is not the HG ROM: a receipt cannot claim one title and ship the other's artifact
    ss = gen4_pins.ROM_SPECS["soulsilver"][0]
    assert _consume(tmp_path, _route_doc(rom_sha1=ss))[0] == "STALE"
    assert _consume(tmp_path, _route_doc(title="soulsilver", rom_sha1=ss))[0] == "PASS"
    assert _consume(tmp_path, _route_doc(title="no_such_title"))[0] == "STALE"
    assert _consume(tmp_path, _route_doc(rom_sha1=""))[0] == "STALE"
    assert _consume(tmp_path, _route_doc(title=""))[0] == "STALE"


def test_b5_a_receipt_of_one_kind_never_passes_as_the_other(tmp_path):
    """B5: the expected kind picks the script, modules and passing statuses."""
    route, catch = _route_doc(), _catch_doc()
    assert (
        _consume(tmp_path, route, "route")[0] == "PASS"
        and _consume(tmp_path, catch, "catch")[0] == "PASS"
    )
    assert _consume(tmp_path, route, "catch")[0] != "PASS"
    assert _consume(tmp_path, catch, "route")[0] != "PASS"
    # a route-status verdict under the catch kind, and a PASS verdict under the route kind, are not passes
    assert _consume(tmp_path, _catch_doc(verdict="PC_DEPOSIT"), "catch")[0] == "FAIL"
    assert _consume(tmp_path, _route_doc(final_status="PASS"), "route")[0] == "FAIL"
    with pytest.raises(KeyError):
        _consume(tmp_path, route, "nonsense")


def test_every_lua_dofile_is_in_the_bound_module_set():
    """The scripts' own dofile/loadfile/require targets must all be hashed in their kind's module set."""
    pat = re.compile(r"""(?:dofile|loadfile|require)\s*\(\s*[^"')]*["']/?([\w./-]+?)["']""")
    for kind, script in (("route", gr.LUA), ("catch", gr.REPO / "lua/tests/probe_gen4_catch.lua")):
        text = script.read_text(encoding="utf-8")
        found = {m.group(1) for m in pat.finditer(text)}
        assert found, f"{script.name}: no dofile target found (pattern drifted)"
        bound = set(gr.RECEIPT_KINDS[kind]["modules"])
        assert {f for f in found if f.endswith(".lua")} <= bound, (kind, found - bound)
    assert {"lua/json_codec.lua", "lua/gen4/reads.lua", "lua/gen4/pk4.lua"} <= set(
        gr.RECEIPT_KINDS["route"]["modules"]
    )
    assert "lua/json_codec.lua" in gr.RECEIPT_KINDS["catch"]["modules"]
    # a script growing an unbound dofile is caught: the check on a synthetic script text
    extra = pat.findall('local X = dofile(REPO .. "/lua/gen4/new_module.lua")')
    assert (
        extra == ["lua/gen4/new_module.lua"] and "lua/gen4/new_module.lua" not in gr.BOUND_MODULES
    )


def test_receipt_binding_is_what_the_run_wrote_and_build_receipt_carries_it(monkeypatch):
    monkeypatch.setattr(gr, "git_head", lambda: "c" * 40)
    b = gr.receipt_binding()
    assert b["source_head"] and b["script"] == "lua/tests/gen4_route_play.lua"
    assert b["script_sha256"] == gr._sha256(gr.LUA)
    assert set(gr.BOUND_MODULES) <= set(b["module_sha256"])
    synth = {"setup": "SYNTH", "sidecar": "s", "sidecar_sha256": "0", "out_sha1": "x"}
    rec = gr.build_receipt(
        "SS", "s.SaveRAM", synth, [], {"status": "PC_DEPOSIT", "detail": "d"}, "f" * 40
    )
    assert {k: rec[k] for k in b if k != "title"} == {k: b[k] for k in b if k != "title"}
    assert (
        rec["title"] == "soulsilver" and rec["rom_sha1"] == "f" * 40
    )  # B4: the title and ROM travel
