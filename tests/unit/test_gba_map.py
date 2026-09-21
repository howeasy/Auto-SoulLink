"""tools/gba_map.py: parse geometry straight from ROM binaries (card gen3-P3-T2).

Every fact below is read from a real ROM, never assumed -- skip cleanly (never fail) when a
ROM isn't present on this machine. Two binaries anchor the checks:

* RR companion build (patch/build/slink_RR.gba), map 5.4 -- coordinator-verified facts from the
  card: 15x10, the only MB_PC (0x83) tile is (11,1), BFS (11,8)->(11,2) is a fixed 10-step path.
* Vanilla FireRed US 1.0 dump, map 3.0 (Pallet Town) -- cross-checked against the pret decomp's
  own data/maps/PalletTown/map.json when that decomp checkout is available locally; otherwise
  checked directly against the physically-verified facts cited on the card (warp coordinates,
  door collision).
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))
import gba_map  # noqa: E402

_RR_ROM = os.path.join(_REPO, "patch", "build", "slink_RR.gba")
_FR_ROM = "E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"
_FR_SYM = os.path.join(_REPO, "data", "gen3", "pret", "pokefirered.sym")
# The pret checkout lives in the REPO ROOT's cache (E:/Google Drive/SLink/.cache/pret/pokefirered),
# not under a worktree: try the worktree first, then the root the worktree was made from.
_ROOT_OF_WORKTREE = _REPO.split(os.sep + ".claude" + os.sep + "worktrees" + os.sep)[0] if (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in _REPO else _REPO
_DECOMP_CANDIDATES = [
    os.path.join(_REPO, ".cache", "pret", "pokefirered", "data", "maps"),
    os.path.join(_ROOT_OF_WORKTREE, ".cache", "pret", "pokefirered", "data", "maps"),
    os.path.join(os.environ.get("SLINK_PRET_CACHE", ""), "pokefirered", "data", "maps"),
]
_DECOMP_MAPS = next((c for c in _DECOMP_CANDIDATES if c and os.path.isdir(c)), _DECOMP_CANDIDATES[0])


def _require_rom(path):
    if not os.path.exists(path):
        pytest.skip(f"ROM not present: {path}")


def test_rr_companion_map_5_4_geometry():
    _require_rom(_RR_ROM)
    rom = gba_map.load(_RR_ROM)
    m = rom.map(5, 4)
    assert (m.width, m.height) == (15, 10)
    assert m.find_behaviour(gba_map.MB_PC) == [(11, 1)]


def test_rr_companion_map_5_4_npc_spawns():
    _require_rom(_RR_ROM)
    rom = gba_map.load(_RR_ROM)
    m = rom.map(5, 4)
    expected = {(2, 3), (4, 7), (7, 2), (8, 2), (10, 6), (12, 5)}
    spawns = {(o.x, o.y) for o in m.objects if (o.x, o.y) in expected}
    assert spawns == expected


def test_rr_companion_map_5_4_bfs():
    _require_rom(_RR_ROM)
    rom = gba_map.load(_RR_ROM)
    m = rom.map(5, 4)
    path = m.bfs((11, 8), (11, 2))
    assert path == [
        "Left", "Up", "Left", "Up", "Up", "Up", "Right", "Right", "Up", "Up",
    ]


def test_fr_pallet_town_geometry_and_warps():
    _require_rom(_FR_ROM)
    rom = gba_map.load(_FR_ROM)
    m = rom.map(3, 0)
    assert (m.width, m.height) == (24, 20)
    warp_xy = {(w.x, w.y) for w in m.warps}
    assert warp_xy == {(6, 7), (15, 7), (16, 13)}
    # House door and lab door: both physically verified as collision-blocked (card gen3-P3-T2 /
    # lua/tests/gen3_scripted_play.lua PATHS comments).
    assert m.collision[7][6] == 1
    assert m.collision[13][16] == 1


def test_fr_groups_addr_resolves_from_sym():
    _require_rom(_FR_ROM)
    if not os.path.exists(_FR_SYM):
        pytest.skip(f".sym not present: {_FR_SYM}")
    rom_default = gba_map.load(_FR_ROM)
    rom_from_sym = gba_map.load(_FR_ROM, sym_path=_FR_SYM)
    assert rom_from_sym.groups_addr == rom_default.groups_addr == gba_map.DEFAULT_GROUPS_ADDR


def test_fr_pallet_town_cross_checked_against_pret_decomp():
    _require_rom(_FR_ROM)
    map_json = os.path.join(_DECOMP_MAPS, "PalletTown", "map.json")
    if not os.path.exists(map_json):
        pytest.skip(f"pret decomp checkout not present: {map_json}")
    with open(map_json, encoding="utf-8") as f:
        decomp = json.load(f)

    rom = gba_map.load(_FR_ROM)
    m = rom.map(3, 0)

    # map.json carries only the layout id; dimensions live in data/layouts/layouts.json
    layouts_json = os.path.join(os.path.dirname(_DECOMP_MAPS), "layouts", "layouts.json")
    with open(layouts_json, encoding="utf-8") as f:
        layouts = {(lay.get("id") or lay.get("name")): lay for lay in json.load(f)["layouts"]}
    lay = layouts[decomp["layout"]]
    assert (m.width, m.height) == (int(lay["width"]), int(lay["height"]))

    decomp_warps = {
        (w["x"], w["y"], w["dest_map"], w["dest_warp_id"])
        for w in decomp.get("warp_events", [])
    }
    rom_warps = {(w.x, w.y, w.map_num, w.warp_id) for w in m.warps}
    assert len(rom_warps) == len(decomp_warps)

    decomp_objects = {(o["x"], o["y"]) for o in decomp.get("object_events", [])}
    rom_objects = {(o.x, o.y) for o in m.objects}
    assert rom_objects == decomp_objects


def test_fr_connections_pallet_route1_viridian():
    """MapHeader.connections (card gen3-P3-C3-14 follow-up, +0x0C -- PHYSICALLY VERIFIED here:
    +0x08, as the card's own text named, decodes to a non-ROM pointer on this binary)."""
    _require_rom(_FR_ROM)
    rom = gba_map.load(_FR_ROM)
    pallet, route1, viridian = rom.map(3, 0), rom.map(3, 19), rom.map(3, 1)

    def by_dir(m):
        return {c.direction: (c.offset, c.map_group, c.map_num) for c in m.connections}

    pallet_c = by_dir(pallet)
    assert pallet_c["up"] == (0, 3, 19)          # -> Route1

    route1_c = by_dir(route1)
    assert route1_c["down"] == (0, 3, 0)         # -> PalletTown
    assert route1_c["up"] == (-12, 3, 1)         # -> ViridianCity

    viridian_c = by_dir(viridian)
    assert viridian_c["down"] == (12, 3, 19)     # -> Route1


def test_fr_arrival_pallet_route1_pair():
    """The two facts the card states outright: Pallet(12,1) up lands on Route1(12,39); Route1
    (12,39) down lands on Pallet(12,0). Both are cross-map connection ARRIVALS, not one-tile-in
    guesses -- the rule lua/tests/gen3_scripted_play.lua's PATHS comments learned the hard way
    (run 13: "start tile (12,0) is not the path's from (12,1)")."""
    _require_rom(_FR_ROM)
    rom = gba_map.load(_FR_ROM)
    pallet, route1 = rom.map(3, 0), rom.map(3, 19)

    assert gba_map.arrival("up", pallet, 12) == (3, 19, 12, 39)
    assert gba_map.arrival("down", route1, 12) == (3, 0, 12, 0)


def test_fr_arrival_route1_viridian_pair():
    """The Route1<->ViridianCity crossing lua/tests/gen3_scripted_play.lua's PATHS also rely on
    (route1_north_to_south_edge's from={12,0}, route1_edge_to_mart_door's to={36,20} via
    ViridianCity(24,39))."""
    _require_rom(_FR_ROM)
    rom = gba_map.load(_FR_ROM)
    route1, viridian = rom.map(3, 19), rom.map(3, 1)

    # Leaving Route1's north edge at x=12 lands on ViridianCity's south row (y=height-1=39).
    assert gba_map.arrival("up", route1, 12) == (3, 1, 24, 39)
    # Leaving ViridianCity's south edge at x=24 lands on Route1's north row (y=0).
    assert gba_map.arrival("down", viridian, 24) == (3, 19, 12, 0)


def test_arrival_returns_none_without_a_matching_connection():
    m = gba_map.Map(width=3, height=3, collision=[[0] * 3] * 3, behaviour=[[0] * 3] * 3)
    assert gba_map.arrival("left", m, 0) is None


def test_fr_connections_cross_checked_against_pret_decomp():
    _require_rom(_FR_ROM)
    for name, group, num in (("PalletTown", 3, 0), ("Route1", 3, 19), ("ViridianCity", 3, 1)):
        map_json = os.path.join(_DECOMP_MAPS, name, "map.json")
        if not os.path.exists(map_json):
            pytest.skip(f"pret decomp checkout not present: {map_json}")
        with open(map_json, encoding="utf-8") as f:
            decomp = json.load(f)
        rom = gba_map.load(_FR_ROM)
        m = rom.map(group, num)
        # map.json spells the direction and names the destination map, not its (group, num);
        # compare direction+offset (what arrival() actually uses), count only for the target.
        decomp_by_dir = {c["direction"]: c["offset"] for c in decomp.get("connections") or []}
        rom_by_dir = {c.direction: c.offset for c in m.connections}
        assert rom_by_dir == decomp_by_dir, name


def test_cli_connections_flag(capsys):
    _require_rom(_FR_ROM)
    rc = gba_map.main([_FR_ROM, "--map", "3.0", "--connections"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "connection up: offset=0 -> 3.19" in out


def test_lua_paths_entry_matches_driver_format():
    entry = gba_map.Map.lua_paths_entry(
        "town_start_to_lab_door", "PalletTown", (6, 9), (16, 14), ["Down", "Right"],
    )
    assert entry == (
        'town_start_to_lab_door = {\n'
        '    map = "PalletTown", from = { 6, 9 }, to = { 16, 14 },\n'
        '    dirs = { "Down", "Right" },\n'
        '},'
    )


def demo():
    """ponytail: smallest runnable check for the BFS/behaviour logic without any ROM."""
    m = gba_map.Map(
        width=3,
        height=3,
        collision=[[0, 0, 0], [0, 1, 0], [0, 0, 0]],
        behaviour=[[0, 0, 0], [0, 0, 0], [0, 0, 0]],
    )
    path = m.bfs((0, 0), (2, 0))
    assert path == ["Right", "Right"], path
    assert m.find_behaviour(0) == [(x, y) for y in range(3) for x in range(3)]
    print("demo ok")


if __name__ == "__main__":
    demo()
