"""tools/gen4_routes.py: path-finding on map data (no emulator). Synthetic grids always run; the
real ROM/pret/save cases skip by name when an input is absent and fail when present but wrong
(tests/TESTING.md)."""

import json
import struct
from pathlib import Path

import pytest

from tools import gen4_routes as gr

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
