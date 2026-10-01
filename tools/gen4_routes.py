#!/usr/bin/env python3
"""Gen 4 (HGSS) scripted-route planner: from the player's saved position to the nearest wild-
encounter grass tile, derived ONLY from ROM / pret data (no screenshots).

    python tools/gen4_routes.py plan [--game HG|hge] --save S.SaveRAM --rom X.nds --pret <pokeheartgold> [--out route.json]
    python tools/gen4_routes.py run  [--game HG|hge]       # live, lane C:/slink/g4/route[_hge]

Sources (pokeheartgold @ad7a3afa; ROM files read through ndspy):
  * Save position (HG; hge reads its own offset from the hge pack, see GAMES): general block +
    0x1234 = array 5 (SAVE_LOCAL_FIELD_DATA,
    include/constants/save_arrays.h:13), whose first member is `currentPosition` = Location
    {mapId, warpId, x, y, direction} (include/field_types_def.h:10-16, Location is 5 x int;
    src/save_local_field_data.c:13-27, the next four members are four more Locations). The
    general block starts at the bank base (server/adapters/gen4_codec.py:417-420 rejects any
    other start), and the block's own 5-Location layout is what pins 0x1234: real-map Locations
    sit at +0x00 and +0x50 only.
  * hge (hg-engine build fc517576): the matrix (a/0/4/1), land data (a/0/6/5) and zone events
    (a/0/3/2) NARCs are byte-identical to HG's (tests/unit/test_gen4_routes.py pins the hashes;
    docs/gen4/research/hge_data_delta.md section 3), so the pret events are reused. hge's
    Location sits at general+0x1424 because its earlier save arrays are larger.
  * Map matrix: NARC a/0/4/1 (NARC_fielddata_mapmatrix_map_matrix = 41), member 0 = "EVERYWHERE",
    the single Johto overworld matrix; layout per src/map_matrix.c `MapMatrix_MapMatrixData_Load`:
    u8 width,height,hasHeaders,hasAltitudes,nameLen,name[],u16 headers[w*h],(u8 alt[w*h]),u16 landIds[w*h].
    Cell index is row-major j*width+i (src/terrain_attributes.c:36-41).
    Location x/y are GLOBAL tile coordinates: cell = (x//32, y//32), tile = (x%32, y%32).
  * Terrain attributes: NARC a/0/6/5 (NARC_fielddata_landdata_land_data = 65), member landId,
    32x32 u16 at +0x14 + extraSize, where extraSize is the u16 at +0x12 (a table of 8-byte
    records between the header and the terrain). MOST members carry a non-zero extra (New Bark's
    land 0 = 0x58, 4 = 0x40, 5 = 0x10, 7-16 = 0x8..0x88, ...), so the fixed 0x14 of
    include/terrain_attributes.h:8 / src/terrain_attributes.c:53 is WRONG for them -- that
    constant only holds for extra == 0 members. Proof, not inference: a warp tile is a door by
    construction, and 312 of the 313 warp tiles in the used banks decode to the door band
    0x68..0x6F at 0x14+extra (162/313 at a fixed 0x14). The member-length identity checked in
    _terrain does NOT discriminate the two layouts -- both satisfy it. Row-major [z*32+x].
    Low byte = tile behaviour (asm/unk_02054648.s:441-446); bit 15 = collision
    (asm/unk_02054648.s:386-395).
  * Encounter grass: MetatileBehavior_IsEncounterGrass == behaviour 2 (src/metatile_behavior.c:11-13,
    TILE_BEHAVIOR_2 == 2). Surfable water = `_020FCA74[b] & 1` (src/metatile_behavior.c:80-82) is
    Surf-GATED, not walkable: Field_PlayerCanSurfOnTile (asm/overlay_01_021F1AFC.s:763-780) and the
    game's blocked predicate sub_02060E54 (asm/unk_0205FD20.s:2155-2181) both refuse it on foot, so
    walkable() blocks it rather than pricing it.
  * Events (global coordinates): files/fielddata/eventdata/zone_event/<bank>_*.json, bank per header
    from src/data/map_headers.h `.eventsBank = NARC_zone_event_<bank>_..._bin`. Warps, bg events and
    NPC tiles+wander ranges are hard-blocked so the walk never fires a script or a warp; coord-event
    triggers are crossable at SOFT_COST and the crossed scriptIds are recorded in the route, since
    a coord event fires on its own var/val (include/map_events_internal.h:40-48) which the planner
    does not evaluate -- the walker clears a self-clearing one with A and resyncs otherwise.
  * Wild table (informational): files/fielddata/encountdata/gs_enc_data.json, entry "map" = header
    short name (include/constants/maps.h comment, e.g. MAP_ROUTE_29 -> R29).

Exit codes: 0 ok, 1 FAIL (present but wrong / refused), 2 SKIP (an input is absent, named).
"""

from __future__ import annotations

import argparse
import heapq
import json
import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server.adapters.gen4_codec import parse_save  # noqa: E402
from tools.gen4_fixtures import (  # noqa: E402
    BIZHAWK_CONFIG,
    FixtureError,
    RomAbsent,
    kill_our_emuhawk,
    lane_dir,
    sha1_of,
    stage_rom,
    stage_save,
    write_nds_run_config,
)

DEFAULT_ROM = Path("E:/Howard/Bizhawk/Pokemon - HeartGold Version (USA).nds")
DEFAULT_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")
DEFAULT_PRET = Path("E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold")
HGE_SAVE = Path("C:/slink/g4/saves/hge_a_OOO_630.SaveRAM")  # owner hge save: Cyndaquil L5, OOO

# Per-title save Location: the pack's profile.location names array 5's general-block offset
# (HG 0x1234, hge 0x1424: hge's earlier arrays are larger) and the Location field offsets. The
# save image carries no array-header table (it lives in the in-RAM SaveData), so the pack's
# FILE-checked `general_off_of_array` is the source; plan_route's matrix map-id check refuses a
# wrong one. game -> (pack profile.json, title key, codec profile, default ROM/save/lane/tag)
HGE_ROM = REPO / ".cache/gen4/hge/build-fc5175764983/test.nds"
GAMES = {
    "HG": (REPO / "data/games/gen4_hgss/profile.json", "heartgold", "hgss"),
    "hge": (REPO / "data/games/gen4_hge/profile.json", "heartgold_hge", "hge"),
}
MATRIX_NARC, LAND_NARC = "a/0/4/1", "a/0/6/5"
TERRAIN_OFF, CELL = 0x14, 32
DOOR_BAND = range(0x68, 0x70)  # TILE_BEHAVIOR_104..111: what a warp tile must decode to
VOID_LAND = 0xFFFF
GRASS = 2
COLLISION = 0x8000
DIRS = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}


class RouteError(ValueError):
    """A route could not be planned (named reason in .reason)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class World:
    """Global tile grid. `land[landId]` is 1024 u16 terrain words; `blocked` = event tiles."""

    width: int  # matrix width in cells
    height: int
    headers: list[int]  # map header id per cell
    lands: list[int]  # land id per cell (0xFFFF = void)
    land: dict[int, tuple[int, ...]]
    blocked: set[tuple[int, int]] = field(default_factory=set)  # warps, bg events, NPC boxes
    soft: set[tuple[int, int]] = field(default_factory=set)  # coord-event triggers: crossable
    # (state-dependent), at a cost
    water: frozenset[int] = frozenset()  # surfable-water behaviours: Surf-gated, never walkable
    names: dict[int, str] = field(default_factory=dict)  # header id -> short name (R29)
    warps: frozenset[tuple[int, int]] = frozenset()  # warp tiles: the door-band oracle
    coord_scripts: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    # coord-event tile -> the scriptIds that can fire there

    def attr(self, x: int, y: int) -> int | None:
        if x < 0 or y < 0:
            return None
        cx, cy = x // CELL, y // CELL
        if cx >= self.width or cy >= self.height:
            return None
        lid = self.lands[cy * self.width + cx]
        if lid == VOID_LAND or lid not in self.land:
            return None
        return self.land[lid][(y % CELL) * CELL + x % CELL]

    def map_at(self, x: int, y: int) -> int | None:
        cx, cy = x // CELL, y // CELL
        if x < 0 or y < 0 or cx >= self.width or cy >= self.height:
            return None
        return self.headers[cy * self.width + cx]

    def walkable(self, x: int, y: int) -> bool:
        """On-foot passable: no collision bit, not an event tile, and NOT surfable water.

        Water is a hard block, not a cost: Field_PlayerCanSurfOnTile
        (asm/overlay_01_021F1AFC.s:763-780) and the game's blocked predicate sub_02060E54
        (asm/unk_0205FD20.s:2155-2181) both gate it behind Surf, and 32,961 of the used land
        tiles are surfable water on collision-clear tiles, so pricing it would plan unwalkable
        rivers. A Surf route needs an explicit opt-in here, not a cheaper number."""
        a = self.attr(x, y)
        return (
            a is not None
            and not a & COLLISION
            and (a & 0xFF) not in self.water
            and (x, y) not in self.blocked
        )

    def is_water(self, x: int, y: int) -> bool:
        a = self.attr(x, y)
        return a is not None and (a & 0xFF) in self.water

    def is_grass(self, x: int, y: int) -> bool:
        a = self.attr(x, y)
        return a is not None and (a & 0xFF) == GRASS and self.walkable(x, y)


# --- loaders ---------------------------------------------------------------------------------
def location_spec(game: str = "HG") -> dict:
    """The pack's save-Location spec for `game` (array id, general-block offset, field offsets)."""
    if game not in GAMES:
        raise RouteError("unknown_game", f"{game!r} is not one of {sorted(GAMES)}")
    path, title, _ = GAMES[game]
    loc = json.loads(_need(path, f"{game} pack").read_text(encoding="utf-8"))["titles"][title][
        "profile"
    ]["location"]
    return {**loc, "general_off": loc["file_cross_check"]["general_off_of_array"]}


def save_position(save_path, game: str = "HG") -> dict:
    """{map, warp, x, y, dir} from the newest bank's LocalFieldData.currentPosition, at the
    general-block offset the `game` pack records (see GAMES)."""
    p = Path(save_path)
    if not p.is_file():
        raise RomAbsent(f"save absent: {p}")
    spec = location_spec(game)
    s = parse_save(p.read_bytes(), GAMES[game][2])
    base = spec["general_off"]
    return {
        k: struct.unpack_from("<i", s.general, base + spec[f"{k}_off"])[0]
        for k in ("map", "warp", "x", "y", "dir")
    }


def _need(path: Path, what: str) -> Path:
    if not Path(path).exists():
        raise RomAbsent(f"{what} absent: {path}")
    return Path(path)


def _parse_header_banks(pret: Path) -> dict[int, int]:
    """header id -> zone_event bank (src/data/map_headers.h + include/constants/maps.h)."""
    ids = {
        n: int(v)
        for n, v in re.findall(
            r"#define (MAP_\w+)\s+(\d+)\b",
            _need(pret / "include/constants/maps.h", "maps.h").read_text(encoding="utf-8"),
        )
    }
    text = _need(pret / "src/data/map_headers.h", "map_headers.h").read_text(encoding="utf-8")
    out = {}
    for name, body in re.findall(r"\[(MAP_\w+)\]\s*=\s*\{(.*?)\n\s*\},", text, re.S):
        m = re.search(r"\.eventsBank\s*=\s*NARC_zone_event_(\d+)_", body)
        if m and name in ids:
            out[ids[name]] = int(m.group(1))
    return out


def _parse_short_names(pret: Path) -> dict[int, str]:
    text = _need(pret / "include/constants/maps.h", "maps.h").read_text(encoding="utf-8")
    return {int(i): s for i, s in re.findall(r"#define MAP_\w+\s+(\d+)\s*//\s*MAP_(\w+)", text)}


def _water_behaviours(pret: Path) -> frozenset[int]:
    text = _need(pret / "src/metatile_behavior.c", "metatile_behavior.c").read_text(
        encoding="utf-8"
    )
    body = re.search(r"_020FCA74\[\]\s*=\s*\{(.*?)\};", text, re.S).group(1)
    return frozenset(
        i for i, v in enumerate(int(t, 16) for t in re.findall(r"0x[0-9A-Fa-f]+", body)) if v & 1
    )


class Events(NamedTuple):
    """Event tiles of the whole overworld, in global coordinates."""

    hard: set[tuple[int, int]]  # warps, bg events, NPC tiles + wander boxes
    soft: set[tuple[int, int]]  # coord-event triggers: crossable, but state-dependent
    warps: frozenset[tuple[int, int]]  # warp tiles alone: every one must decode to a door
    coord_scripts: dict[tuple[int, int], tuple[int, ...]]  # coord tile -> its scriptIds


def _event_tiles(pret: Path, banks: dict[int, int], headers: set[int]) -> Events:
    """Event tiles. Hard = warps, bg events, NPCs with their wander box. Soft = coord-event
    triggers: a coord event fires on its own var/val, which the planner does not evaluate, so it
    may cross one at a cost -- the walker clears a self-clearing script with A and resyncs, and
    the crossed scriptIds travel in the route so a stuck leg names the culprit."""
    edir = _need(pret / "files/fielddata/eventdata/zone_event", "zone_event json dir")
    out: set[tuple[int, int]] = set()
    warps: set[tuple[int, int]] = set()
    soft: set[tuple[int, int]] = set()
    scripts: dict[tuple[int, int], set[str]] = {}
    for bank in sorted({banks[h] for h in headers if h in banks}):
        for f in edir.glob(f"{bank:03d}_*.json"):
            d = json.loads(f.read_text(encoding="utf-8"))
            for w in d.get("warps", []):
                out.add((w["x"], w["z"]))
                warps.add((w["x"], w["z"]))
            for b in d.get("bgs", []):
                out.add((b["x"], b["z"]))
            for c in d.get("coords", []):
                for i in range(c["w"]):
                    for j in range(c["h"]):
                        t = (c["x"] + i, c["z"] + j)
                        soft.add(t)
                        scripts.setdefault(t, set()).add(c["scriptId"])
            for o in d.get("objects", []):
                xr, yr = o.get("xRange", 0), o.get("yRange", 0)
                out.update(
                    (o["x"] + i, o["z"] + j) for i in range(-xr, xr + 1) for j in range(-yr, yr + 1)
                )
    soft -= out
    return Events(out, soft, frozenset(warps), {t: tuple(sorted(v)) for t, v in scripts.items()})


def _terrain(f: bytes, lid: int) -> tuple[int, ...]:
    """32x32 terrain words of one land-data member. Header: u32 terrainSize(0x800), objectSize,
    modelSize, bdhcSize, then u32 {u16 0x1234, u16 extraSize}; `extraSize` bytes (a table of
    8-byte records) sit between the header and the terrain, so terrain = 0x14 + extraSize. Most
    members carry a non-zero extra, and the decomp's fixed 0x14 (include/terrain_attributes.h:8)
    is only right for the rest -- see the module docstring for the door-band proof. The length
    identity below is a sanity check, not the proof: both layouts satisfy it."""
    sizes = struct.unpack_from("<4I", f, 0)
    magic, extra = struct.unpack_from("<HH", f, 0x10)
    if magic != 0x1234 or sizes[0] != 0x800 or TERRAIN_OFF + extra + sum(sizes) != len(f):
        raise FixtureError(
            f"land_data member {lid}: unexpected layout (sizes {sizes}, magic "
            f"{magic:#x}, extra {extra:#x}, len {len(f):#x})"
        )
    return struct.unpack_from("<1024H", f, TERRAIN_OFF + extra)


def _matrix_members(pret: Path) -> dict[int, int]:
    """header id -> map-matrix NARC member (`.matrixId = NARC_map_matrix_map_matrix_0071_...`)."""
    ids = {
        n: int(v)
        for n, v in re.findall(
            r"#define (MAP_\w+)\s+(\d+)",
            _need(pret / "include/constants/maps.h", "maps.h").read_text(encoding="utf-8"),
        )
    }
    text = _need(pret / "src/data/map_headers.h", "map_headers.h").read_text(encoding="utf-8")
    return {
        ids[name]: int(m.group(1))
        for name, body in re.findall(r"\[(MAP_\w+)\]\s*=\s*\{(.*?)\n\s*\},", text, re.S)
        if name in ids
        and (m := re.search(r"\.matrixId\s*=\s*NARC_map_matrix_map_matrix_(\d+)_", body))
    }


def load_world(rom_path=DEFAULT_ROM, pret=DEFAULT_PRET, matrix=0, header=None) -> World:
    """Johto overworld by default (matrix member 0). An interior is a 1x1 matrix member whose
    cell has no header table: pass its `matrix` member and its `header` id (see _matrix_members);
    interior tile coordinates are local, as in its zone_event warps/objects."""
    import ndspy.narc
    import ndspy.rom

    rom_path, pret = Path(rom_path), Path(pret)
    _need(rom_path, "ROM")
    _need(pret, "pret source")
    rom = ndspy.rom.NintendoDSRom.fromFile(str(rom_path))
    mat = ndspy.narc.NARC(rom.getFileByName(MATRIX_NARC)).files[matrix]
    land = ndspy.narc.NARC(rom.getFileByName(LAND_NARC))
    w, h, has_hdr, has_alt, nlen = mat[:5]
    o = 5 + nlen
    n = w * h
    headers = list(struct.unpack_from(f"<{n}H", mat, o)) if has_hdr else [header or 0] * n
    o += 2 * n if has_hdr else 0
    o += n if has_alt else 0
    lands = list(struct.unpack_from(f"<{n}H", mat, o))
    used = sorted({lid for lid in lands if lid != VOID_LAND})
    terrain = {lid: _terrain(bytes(land.files[lid]), lid) for lid in used}
    banks = _parse_header_banks(pret)
    present = {hd for hd, lid in zip(headers, lands, strict=True) if lid != VOID_LAND}
    ev = _event_tiles(pret, banks, present)
    return World(
        w,
        h,
        headers,
        lands,
        terrain,
        ev.hard,
        ev.soft,
        _water_behaviours(pret),
        _parse_short_names(pret),
        ev.warps,
        ev.coord_scripts,
    )


# --- planning --------------------------------------------------------------------------------
SOFT_COST = 60  # extra step cost on a coord-event tile (crossable, but it may fire a script)
SEARCH_LIMIT = 600_000  # settled nodes; over it is a named refusal, not "no grass"


def _search(world: World, start: tuple[int, int], goal_ok, limit: int = 600_000):
    """Dijkstra (unit steps, SOFT_COST extra on a coord-event tile): cheapest path to a goal."""
    best = {start: 0}
    prev = {start: None}
    heap = [(0, start)]
    while heap:
        cost, cur = heapq.heappop(heap)
        if cost > best[cur]:
            continue
        if goal_ok(cur):
            path = []
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        if len(best) > limit:
            raise RouteError(
                "search_budget", f"{len(best)} nodes settled (limit {limit}); raise the limit"
            )
        for dx, dy in DIRS.values():
            nxt = (cur[0] + dx, cur[1] + dy)
            if world.walkable(*nxt):
                c = cost + 1 + (SOFT_COST if nxt in world.soft else 0)
                if c < best.get(nxt, 1 << 60):
                    best[nxt] = c
                    prev[nxt] = cur
                    heapq.heappush(heap, (c, nxt))
    return None


def _dir_of(a: tuple[int, int], b: tuple[int, int]) -> str:
    return next(n for n, (dx, dy) in DIRS.items() if (a[0] + dx, a[1] + dy) == b)


def _pace_pair(world: World, t: tuple[int, int]) -> tuple[int, int] | None:
    for d in ("Right", "Left"):
        n = (t[0] + DIRS[d][0], t[1] + DIRS[d][1])
        if world.is_grass(*n):
            return n
    return None


def plan_route(world: World, start: dict, wild_lookup=None, game: str = "HG") -> dict:
    """Walk from `start` ({map,x,y,dir}) to the nearest grass tile that has a horizontal grass
    neighbour (the pace pair). Refuses a start whose map id does not match the matrix."""
    sx, sy = start["x"], start["y"]
    actual = world.map_at(sx, sy)
    if actual != start["map"]:
        raise RouteError(
            "map_mismatch", f"save says map {start['map']} but ({sx},{sy}) is in map {actual}"
        )
    if world.attr(sx, sy) is None:
        raise RouteError("start_off_map", f"({sx},{sy}) has no land data")
    # the start tile is exempt from the event block (the player is standing on it), and the
    # exemption is per call: `world` is copied, never mutated, so a reused World keeps its events
    w = replace(world, blocked=world.blocked - {(sx, sy)})
    path = _search(
        w, (sx, sy), lambda t: w.is_grass(*t) and _pace_pair(w, t) is not None, SEARCH_LIMIT
    )
    if not path:
        raise RouteError(
            "no_grass_reachable", f"no walkable path from ({sx},{sy}) to encounter grass"
        )
    first_grass = next(i for i, t in enumerate(path) if w.is_grass(*t))
    pace_b = _pace_pair(w, path[-1])
    # run-length segments, split so the grass edge (last non-grass tile) is a segment end
    steps, edge_idx = [], None
    for i in range(1, len(path)):
        d = _dir_of(path[i - 1], path[i])
        if steps and steps[-1]["dir"] == d and i != first_grass:
            steps[-1]["n"] += 1
            steps[-1]["to"] = _loc(world, path[i])
        else:
            steps.append({"dir": d, "n": 1, "to": _loc(world, path[i])})
        if i == first_grass - 1:
            edge_idx = len(steps) - 1
    pace_dir = _dir_of(path[-1], pace_b)
    mid = world.map_at(*path[-1])
    route = {
        "version": 1,
        "game": game,
        "start": {**_loc(world, (sx, sy)), "dir": start.get("dir")},
        "steps": steps,
        "grass_edge_after_step": edge_idx,  # None when the start is already on/at the grass
        "grass": {
            "enter": _loc(world, path[first_grass]),
            "tile": _loc(world, path[-1]),
            "pace": {
                "a": [path[-1][0], path[-1][1]],
                "b": list(pace_b),
                "dir_ab": pace_dir,
                "dir_ba": _dir_of(pace_b, path[-1]),
                "max_steps": 4000,
            },
        },
        "tiles": len(path) - 1,
        # every grass tile the walk steps on before the pace tile: a wild encounter can fire on
        # any of them, so the harness polls the battle chain for a task there
        "approach_grass": [list(t) for t in path[:-1] if w.is_grass(*t)],
        "soft_events": [
            {"x": t[0], "y": t[1], "scriptIds": list(world.coord_scripts.get(t, ()))}
            for t in path
            if t in world.soft
        ],
        # invariant: water is blocked, so this must stay empty -- a non-empty list means
        # walkable() regressed to pricing water
        "water_tiles": [list(t) for t in path if world.is_water(*t)],
        "map_name": world.names.get(mid),
    }
    if wild_lookup:  # hge's encounter NARC a/0/3/7 is byte-identical (hge_data_delta.md section 1)
        route["wild_land_hg_day"] = wild_lookup(world.names.get(mid))
    return route


# --- errands: a one-NPC house visit that a story gate demands before the route is walkable ----------
# An hge save (and any save taken before Mom hands over the Pokegear) cannot leave New Bark west:
# coord event T20_002 fires on every pass and walks the player back (scr_seq_0842_T20.s:269-,
# `GoToIfSet FLAG_GOT_POKEGEAR`; the Pokegear is given by Mom in the player's house,
# scr_seq_0845_T20R0201.s:116-124). The errand is enter -> talk -> exit, one leg each; every leg
# re-plans from the position the previous one logged, like a cutscene resync.
ERRANDS = {"pokegear": ("MAP_NEW_BARK_PLAYER_HOUSE_1F", "obj_T20R0201_gsmama")}
ERRAND_PHASES = ("enter", "talk", "exit")


@dataclass
class Errand:
    house_id: int
    outer_id: int
    house: World  # the interior (local coordinates)
    door_out: tuple[int, int]  # the outdoor warp tile into the house
    door_in: tuple[int, int]  # the interior warp tile back out
    npc: tuple[int, int]


def _bank_json(pret: Path, bank: int) -> list[dict]:
    edir = _need(pret / "files/fielddata/eventdata/zone_event", "zone_event json dir")
    return [
        json.loads(f.read_text(encoding="utf-8")) for f in sorted(edir.glob(f"{bank:03d}_*.json"))
    ]


def load_errand(rom_path, pret, name: str, outer_id: int) -> Errand:
    if name not in ERRANDS:
        raise RouteError("unknown_errand", f"{name!r} is not one of {sorted(ERRANDS)}")
    house_const, npc_id = ERRANDS[name]
    pret = Path(pret)
    ids = {
        n: int(v)
        for n, v in re.findall(
            r"#define (MAP_\w+)\s+(\d+)\b",
            _need(pret / "include/constants/maps.h", "maps.h").read_text(encoding="utf-8"),
        )
    }
    house_id = ids[house_const]
    banks = _parse_header_banks(pret)
    house = load_world(rom_path, pret, _matrix_members(pret)[house_id], house_id)
    outer_names = {n for n, v in ids.items() if v == outer_id}
    door_out = [
        (w["x"], w["z"])
        for d in _bank_json(pret, banks[outer_id])
        for w in d.get("warps", [])
        if w["header"] == house_const
    ]
    inner = _bank_json(pret, banks[house_id])
    door_in = [
        (w["x"], w["z"]) for d in inner for w in d.get("warps", []) if w["header"] in outer_names
    ]
    npc = [(o["x"], o["z"]) for d in inner for o in d.get("objects", []) if o["id"] == npc_id]
    if len(door_out) != 1 or len(door_in) != 1 or len(npc) != 1:
        raise RouteError(
            "errand_data",
            f"{name}: door_out={door_out} door_in={door_in} npc={npc} ({house_const})",
        )
    return Errand(house_id, outer_id, house, door_out[0], door_in[0], npc[0])


def _runs(world: World, path: list[tuple[int, int]]) -> list[dict]:
    steps: list[dict] = []
    for a, b in zip(path, path[1:], strict=False):
        d = _dir_of(a, b)
        if steps and steps[-1]["dir"] == d:
            steps[-1]["n"] += 1
            steps[-1]["to"] = _loc(world, b)
        else:
            steps.append({"dir": d, "n": 1, "to": _loc(world, b)})
    return steps


def plan_errand(world: World, errand: Errand, phase: str, start: dict, game: str = "HG") -> dict:
    """One errand leg from `start`: enter (outdoors -> door), talk (house -> beside Mom, facing
    her), exit (house -> door). The tile in front of a door/NPC is the goal; the door step is
    flagged `warp` and the NPC turn is `talk.face`."""
    if phase not in ERRAND_PHASES:
        raise RouteError("unknown_phase", phase)
    if phase == "enter":
        w, target, dest = world, errand.door_out, errand.house_id
    else:
        w, target, dest = errand.house, errand.npc if phase == "talk" else errand.door_in, None
    sx, sy = start["x"], start["y"]
    actual = w.map_at(sx, sy)
    if actual != start["map"]:
        raise RouteError(
            "map_mismatch", f"start map {start['map']} but ({sx},{sy}) is in map {actual}"
        )
    free = replace(w, blocked=w.blocked - {(sx, sy)})
    path = _search(
        free,
        (sx, sy),
        lambda t: abs(t[0] - target[0]) + abs(t[1] - target[1]) == 1,
        SEARCH_LIMIT,
    )
    if not path:
        raise RouteError("no_path", f"{phase}: no walkable tile beside {target} from ({sx},{sy})")
    steps = _runs(w, path)
    last = path[-1]
    route = {
        "version": 1,
        "game": game,
        "kind": "errand",
        "phase": phase,
        "start": {**_loc(w, (sx, sy)), "dir": start.get("dir")},
        "steps": steps,
        "tiles": len(path) - 1,
    }
    if phase == "talk":
        route["talk"] = {"face": _dir_of(last, target)}
    else:  # the door step: arrival coordinates are not assumed, the leg logs them
        dest = dest if dest is not None else errand.outer_id
        steps.append(
            {
                "dir": _dir_of(last, target),
                "n": 1,
                "warp": True,
                "to": {"map": dest, "x": -1, "y": -1},
            }
        )
    return route


def _loc(world: World, t: tuple[int, int]) -> dict:
    return {"map": world.map_at(*t), "x": t[0], "y": t[1]}


def wild_land_day(pret: Path):
    """Callable short-name -> [(species, level)] for HG day land encounters (informational)."""
    data = json.loads(
        _need(
            Path(pret) / "files/fielddata/encountdata/gs_enc_data.json", "gs_enc_data.json"
        ).read_text(encoding="utf-8")
    )["encounters"]

    def pick(v, key):
        return v.get(key, v) if isinstance(v, dict) and key in v else v

    def look(name):
        for e in data:
            if e.get("map") == name and "land" in e:
                out = []
                for m in e["land"]["mons"]:
                    sp = pick(pick(m["species"], "day"), "HEARTGOLD")
                    out.append((sp, pick(m["level"], "HEARTGOLD")))
                return out
        return None

    return look


def replay(world: World, route: dict) -> list[tuple[int, int]]:
    """Expand a route's steps to the tile list (used by tests/Lua cross-check)."""
    x, y = route["start"]["x"], route["start"]["y"]
    tiles = [(x, y)]
    for s in route["steps"]:
        dx, dy = DIRS[s["dir"]]
        for _ in range(s["n"]):
            x, y = x + dx, y + dy
            tiles.append((x, y))
    return tiles


# --- live run (one EmuHawk per leg, own lane, bounded) ----------------------------------------
EMUHAWK = Path("E:/Howard/Bizhawk/EmuHawk.exe")
LUA = REPO / "lua" / "tests" / "gen4_route_play.lua"


def parse_result(log: str) -> dict:
    """The last `RESULT <status> ...` line of a Lua log -> {status, detail, lines}."""
    res = {"status": "NO_RESULT", "detail": "", "lines": log.splitlines()}
    for ln in res["lines"]:
        m = re.search(r"RESULT (\w+)\s*(.*)$", ln)
        if m:
            res["status"], res["detail"] = m.group(1), m.group(2)
    return res


def run_lane(
    rom=DEFAULT_ROM,
    save=DEFAULT_SAVE,
    pret=DEFAULT_PRET,
    *,
    game="HG",
    errand=None,
    lane="route",
    tag="route",
    initial_time="2010-01-01T12:00:00",
    timeout=900,
    max_legs=4,
    pace_max=None,
) -> dict:
    """Plan + drive the route live. Leg 1 boots the staged save copy; a RESYNC (a coord-event
    cutscene advanced with A) saves a state, the next leg re-plans from the logged position and
    resumes from that state. `errand` ("pokegear") prepends the enter/talk/exit legs of a house
    visit (see ERRANDS). Returns the last leg's parsed result."""
    ld = lane_dir(lane)
    ld.mkdir(parents=True, exist_ok=True)
    write_nds_run_config(
        BIZHAWK_CONFIG,
        ld / "bizhawk.ini",
        initial_time=initial_time,
        lane_saveram_dir=ld / "SaveRAM",
    )
    rom_staged = stage_rom(rom, ld)
    stage_save(save, ld, sha1_of(rom_staged), rom_basename=rom_staged.name)
    world = load_world(rom, pret)
    start = save_position(save, game)
    err = load_errand(rom, pret, errand, start["map"]) if errand else None
    phases = list(ERRAND_PHASES) if err else []
    max_legs += len(phases)
    load_state = ""
    result: dict = {}
    for leg in range(1, max_legs + 1):
        leg_start = start
        if phases:
            route = plan_errand(world, err, phases.pop(0), start, game)
        else:
            route = plan_route(world, start, wild_land_day(Path(pret)), game)
        rpath = ld / f"{tag}_leg{leg}.json"
        rpath.write_text(json.dumps(route, indent=1), encoding="utf-8")
        log = ld / f"{tag}_leg{leg}.log"
        log.unlink(missing_ok=True)
        env = dict(
            os.environ,
            G4_REPO=str(REPO).replace("\\", "/"),
            G4_ROUTE=str(rpath).replace("\\", "/"),
            G4_OUT=str(log).replace("\\", "/"),
            G4_LANE=str(ld).replace("\\", "/"),
            G4_TAG=f"{tag}_leg{leg}",
            G4_LOAD_STATE=load_state,
        )
        if pace_max:
            env["G4_PACE_MAX"] = str(pace_max)
        cmd = [str(EMUHAWK), f"--config={ld / 'bizhawk.ini'}", f"--lua={LUA}", str(rom_staged)]
        t0 = time.time()
        try:
            proc = subprocess.Popen(cmd, cwd=str(ld), env=env)
        except FileNotFoundError as exc:  # a named skip, like every other absent input
            raise RomAbsent(f"emulator absent: {cmd[0]}") from exc
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # a clean exit has already reaped it; do not taskkill a pid we no longer own
            if proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            kill_our_emuhawk(ld)
        result = parse_result(log.read_text(encoding="utf-8") if log.exists() else "")
        result.update(leg=leg, wall=round(time.time() - t0, 1), route=route, log=str(log))
        if result["status"] != "RESYNC":
            return result
        m = re.search(r"map=(-?\d+) x=(-?\d+) y=(-?\d+) dir=(-?\d+) state=(.+)$", result["detail"])
        if not m:
            return result
        start = {"map": int(m[1]), "x": int(m[2]), "y": int(m[3]), "dir": int(m[4])}
        load_state = m[5].strip()
        if route.get("kind") != "errand" and (start["map"], start["x"], start["y"]) == (
            leg_start["map"],
            leg_start["x"],
            leg_start["y"],
        ):  # the same script fired again and put us back: re-planning would repeat it forever
            result["status"] = "RESYNC_LOOP"
            return result
    return result


# --- CLI -------------------------------------------------------------------------------------
def _defaults(a) -> None:
    """Fill the per-game defaults for options left unset (hge: its own ROM, save, lane, tag)."""
    hge = a.game == "hge"
    a.rom = a.rom or str(HGE_ROM if hge else DEFAULT_ROM)
    a.save = a.save or str(HGE_SAVE if hge else DEFAULT_SAVE)
    a.pret = a.pret or str(DEFAULT_PRET)
    if hasattr(a, "lane"):
        a.lane = a.lane or ("route_hge" if hge else "route")
        a.tag = a.tag or a.lane


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    r = sub.add_parser("run", help="plan and drive the route live in lane C:/slink/g4/route[_hge]")
    for q in (p, r):
        q.add_argument("--game", choices=sorted(GAMES), default="HG")
        q.add_argument("--save")
        q.add_argument("--rom")
        q.add_argument("--pret")
    p.add_argument("--out")
    r.add_argument("--lane")
    r.add_argument("--tag", help="state/log name prefix (default: the lane name)")
    r.add_argument("--errand", choices=sorted(ERRANDS), help="house visit before the route")
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--pace-max", type=int)
    a = ap.parse_args(argv)
    _defaults(a)
    if a.cmd == "run":
        try:
            res = run_lane(
                a.rom,
                a.save,
                a.pret,
                game=a.game,
                errand=a.errand,
                lane=a.lane,
                tag=a.tag,
                timeout=a.timeout,
                pace_max=a.pace_max,
            )
        except RomAbsent as exc:
            print(f"SKIP: {exc}", file=sys.stderr)
            return 2
        except (RouteError, FixtureError, ValueError, OSError) as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print("\n".join(res["lines"]))
        print(f"leg {res['leg']} wall {res['wall']}s status {res['status']} {res['detail']}")
        return 0 if res["status"] == "BATTLE" else 1
    try:
        start = save_position(a.save, a.game)
        world = load_world(a.rom, a.pret)
        route = plan_route(world, start, wild_land_day(Path(a.pret)), a.game)
    except RomAbsent as exc:
        print(f"SKIP: {exc}", file=sys.stderr)
        return 2
    except (RouteError, FixtureError, ValueError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(route, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text, encoding="utf-8")
        print(
            f"wrote {a.out}: {route['tiles']} tiles, {len(route['steps'])} segments, grass {route['grass']['tile']}"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
