"""Regression coverage for docs/gen3/research/rr_fixture_route_2026-09-24.md (cards
G5-RR-FIXTURE-ROUTE / G5-RR-FIXTURE-DRIVER).

Two kinds of fact, both read straight from the admitted clean RR 4.1 ROM, never from a
screenshot or an assumption carried over from vanilla FireRed:

* map/BFS geometry (tools/gba_map.py), pinned to the exact direction lists
  lua/tests/gen3_rr_battle_fixture.lua's PATHS table hardcodes for its `route2` leg -- a change
  in ANY of these would silently break that leg's walk, so a change here must be a deliberate,
  reviewed re-pin of both files together;
* the RR ROM's own compiled event-script bytecode (map_script/object_event/opcode tables from
  the cached pret pokefirered checkout's asm/macros/{map,event}.inc), anchored the same way
  server/adapters/gen3_codec.py's verify_rr_save_layout_rom anchors the save layout: exact bytes
  at exact file offsets, never a live emulator read.

Every test skips cleanly (never fails) when the clean ROM or the pret checkout is not present on
this machine -- the same convention tests/unit/test_gba_map.py already uses.

NO EMULATOR. These are static, ROM/decomp-only facts (owner rule: no vision for game facts).
"""
from __future__ import annotations

import os
import sys

import pytest

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "tools"))
import gba_map  # noqa: E402

_RR_CLEAN_ROM = "E:/Google Drive/SLink/Pokemon - Radical Red.gba"
_RR_CLEAN_MD5 = "8529f3a45d32bce4da637976fcf269d4"


def _require_rom(path):
    if not os.path.exists(path):
        pytest.skip(f"ROM not present: {path}")


def _load():
    _require_rom(_RR_CLEAN_ROM)
    return gba_map.load(_RR_CLEAN_ROM)


def _anchor(rom, addr, expected_hex):
    """One exact byte run at one ROM address (0x08000000-based), file-offset resolved the same
    way gba_map.Rom's own readers do (_addr_to_offset) -- never re-derived per call site."""
    off = gba_map._addr_to_offset(addr)
    expected = bytes.fromhex(expected_hex)
    actual = rom.data[off:off + len(expected)]
    assert actual == expected, (
        f"0x{addr:08X} (file offset 0x{off:X}): got {actual.hex()}, want {expected_hex}")


# ── map geometry / BFS: must match lua/tests/gen3_rr_battle_fixture.lua's PATHS table ─────────

def test_clean_rom_md5_matches_the_card():
    _require_rom(_RR_CLEAN_ROM)
    import hashlib
    with open(_RR_CLEAN_ROM, "rb") as f:
        digest = hashlib.md5(f.read()).hexdigest()
    assert digest == _RR_CLEAN_MD5


def test_route1_viridian_pallet_connections():
    rom = _load()
    route1 = rom.map(3, 19)
    viridian = rom.map(3, 1)
    conns = {c.direction: (c.offset, c.map_group, c.map_num) for c in route1.connections}
    assert conns["up"] == (-12, 3, 1)     # -> ViridianCity
    assert conns["down"] == (0, 3, 0)     # -> PalletTown
    v_conns = {c.direction: (c.offset, c.map_group, c.map_num) for c in viridian.connections}
    assert v_conns["down"] == (12, 3, 19)  # -> Route1


def test_no_hidden_items_near_the_fixture():
    """BG_EVENT_HIDDEN_ITEM (kind=7) on Route1/Viridian/Pallet and their nine indoor maps: none.
    Candidate 2 (an item ball on the ground) in the research doc is rejected on this fact."""
    rom = _load()
    maps = [(3, 19), (3, 1), (3, 0), (4, 0), (4, 1), (4, 2), (4, 3),
            (5, 0), (5, 1), (5, 2), (5, 3), (5, 4)]
    for grp, num in maps:
        m = rom.map(grp, num)
        hidden = [b for b in m.bg if b.kind == 7]
        assert hidden == [], f"map {grp}.{num} has a hidden item: {hidden}"


def test_route1_grass_to_north_edge_bfs():
    rom = _load()
    m = rom.map(3, 19)
    path = m.bfs((12, 37), (12, 0))
    assert path == [
        "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Left", "Up", "Up", "Up",
        "Up", "Up", "Right", "Right", "Right", "Right", "Up", "Up", "Up", "Up", "Up",
        "Up", "Left", "Left", "Up", "Up", "Up", "Up", "Right", "Right", "Right", "Right",
        "Right", "Right", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up",
        "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Left", "Up", "Up", "Left",
    ]


def test_viridian_arrival_to_mart_door_bfs():
    rom = _load()
    m = rom.map(3, 1)
    path = m.bfs((24, 39), (36, 20))
    assert path == [
        "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Left", "Left", "Up", "Up", "Up",
        "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Right", "Right", "Right",
        "Right", "Right", "Right", "Right", "Right", "Right", "Right", "Right", "Right",
        "Right", "Right",
    ]
    assert m.bfs((36, 20), (24, 39)) == [
        "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
        "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left", "Left",
        "Left", "Left", "Left", "Left", "Left", "Down", "Down", "Down", "Down",
        "Down", "Down", "Down", "Down", "Down", "Down", "Right", "Right",
    ]


def test_route1_north_edge_to_south_edge_bfs():
    rom = _load()
    m = rom.map(3, 19)
    assert m.bfs((12, 0), (12, 39)) == [
        "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right", "Down",
        "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
        "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left", "Left",
        "Left", "Left", "Down", "Down", "Down", "Down", "Down", "Right", "Right",
        "Down", "Down", "Down", "Down", "Down", "Down", "Left", "Left", "Left",
        "Left", "Down", "Down", "Down", "Down", "Down", "Right", "Right", "Right",
        "Right", "Down", "Down", "Down", "Down",
    ]
    assert m.bfs((12, 39), (12, 37)) == ["Up", "Up"]


def test_pallet_lab_door_bfs():
    rom = _load()
    m = rom.map(3, 0)
    assert m.bfs((12, 0), (16, 14)) == [
        "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down", "Down",
        "Down", "Down", "Down", "Down", "Right", "Right", "Right", "Right",
    ]
    assert m.bfs((16, 14), (12, 0)) == [
        "Left", "Left", "Left", "Left", "Up", "Up", "Up", "Up", "Up", "Up", "Up", "Up",
        "Up", "Up", "Up", "Up", "Up", "Up",
    ]


def test_oakslab_entrance_to_oak_bfs():
    """Warp array-index correspondence, not a warp_id-value match: PalletTown's lab door warp
    (16,13) declares warp_id=0, so it targets OaksLab's warp ARRAY INDEX 0, (6,12) -- the
    lab.warps[0] entry, regardless of that entry's own stored warp_id field (all three of
    OaksLab's warps store warp_id=2, which is Pallet's own array index for the SAME door, the
    return trip)."""
    rom = _load()
    pallet = rom.map(3, 0)
    lab = rom.map(4, 3)
    lab_door = next(w for w in pallet.warps if w.map_group == 4 and w.map_num == 3)
    assert lab_door.warp_id == 0
    entrance = (lab.warps[lab_door.warp_id].x, lab.warps[lab_door.warp_id].y)
    assert entrance == (6, 12)
    assert lab.bfs(entrance, (6, 4)) == ["Up"] * 8
    oak = next(o for o in lab.objects if (o.x, o.y) == (6, 3))
    assert oak.movement_type == 8   # MOVEMENT_TYPE_FACE_DOWN


# ── RR's own compiled event-script bytecode: the flag/var ids this route depends on ───────────
# Every anchor is a `.byte`/`.2byte`/`.4byte` sequence an asm/macros/{map,event}.inc macro would
# assemble, decoded by hand against that same opcode table (docs/gen3/research/
# rr_fixture_route_2026-09-24.md "RR bytecode disassembly" section carries the full narrative
# decode this file only anchors).

def test_mart_on_frame_table_gates_on_var_0x4057():
    rom = _load()
    # header_ptr(5,3)+0x08 (mapScripts): type=1 -> OnLoad@0x0816a1de; type=2 (ON_FRAME_TABLE) ->
    # 0x0816a1fb; end(0).
    _anchor(rom, 0x0816a1d3, "01dea1160802fba1160800")
    # ON_FRAME_TABLE's one entry: var=0x4057 compare=0 script=0x0816a205; end(0).
    _anchor(rom, 0x0816a1fb, "5740000005a216080000")


def test_mart_on_load_checks_pokedex_flag_0x829():
    rom = _load()
    # checkflag 0x829 ; goto_if 0(FALSE), 0x0816a1e8 ; end
    _anchor(rom, 0x0816a1de, "2b29080600e8a1160802")


def test_mart_parcel_scene_sets_var_0x4057_and_gives_the_parcel():
    rom = _load()
    _anchor(rom, 0x0816a205, "69c7004f0100ed751a08")  # lockall; textcolor 0; applymovement...
    # setvar 0x4057,1 ; additem item=0x15d(349=ITEM_OAKS_PARCEL) qty=1 ; loadword 0,...
    _anchor(rom, 0x0816a234, "1657400100445d0101000f")
    _anchor(rom, 0x0816a255, "16554005006b02")  # setvar 0x4055,5 ; releaseall ; end


def test_mart_clerk_refuses_to_sell_while_var_0x4057_is_1():
    rom = _load()
    # lock; faceplayer; compare_var_to_value 0x4057,1; goto_if 1(EQUAL),0x0871c7a0
    _anchor(rom, 0x0871c6c0, "6a5a21574001000601a0c771")


def test_oak_gates_the_dex_scene_on_var_0x4057_ge_1():
    rom = _load()
    _anchor(rom, 0x09050959, "6a5a470b0101")  # lock; faceplayer; checkitem 0x10b,1
    # compare_var_to_value 0x4057,1 ; goto_if 4(>=), 0x0816961e (ReceiveDexScene)
    _anchor(rom, 0x090509a0, "215740010006041e961608")


def test_oak_receive_dex_scene_gives_ten_poke_balls():
    rom = _load()
    _anchor(rom, 0x08169637, "455d010100")   # removeitem 0x15d(OAKS_PARCEL),1
    _anchor(rom, 0x0816976d, "292908")       # setflag 0x829 (FLAG_SYS_POKEDEX_GET)
    _anchor(rom, 0x08169780, "4404000a00")   # additem item=4(ITEM_POKE_BALL), qty=10 -- not 5
    # setvar 0x4055,6 ; setvar 0x4057,2 ; setvar 0x4051,1
    _anchor(rom, 0x0816982a, "165540060016574002001651400100")
