#!/usr/bin/env python3
"""Gen 4 (HGSS) scripted-route planner: from the player's saved position to the nearest wild-
encounter grass tile, derived ONLY from ROM / pret data (no screenshots).

    python tools/gen4_routes.py plan [--game HG|hge] --save S.SaveRAM --rom X.nds --pret <pokeheartgold> [--out route.json]
    python tools/gen4_routes.py run  [--game HG|hge]       # live, lane <LANE_ROOT>/route[_hge]

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
import hashlib
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

from server.adapters.gen4_codec import counter_newer, mon_key, parse_save  # noqa: E402
from tools import gen4_evidence, gen4_pins  # noqa: E402
from tools.gen4_fixtures import (  # noqa: E402
    BIZHAWK_CONFIG,
    FixtureError,
    RomAbsent,
    kill_our_emuhawk,
    lane_dir,
    lane_root,
    sha1_of,
    stage_rom,
    stage_save,
    write_nds_run_config,
)


def route_pacing(settings, rate=300):
    """Requested pacing for route/diagnostic producers, independent of owner UI defaults."""
    if not isinstance(rate, int) or isinstance(rate, bool) or not 0 < rate <= 1000:
        raise ValueError("invalid requested route rate")
    return {**settings, "SpeedPercent": rate, "ClockThrottle": True, "Unthrottled": False,
            "FrameSkip": 0, "AutoMinimizeSkipping": False, "VSyncThrottle": False,
            "SuperHawkThrottle": False}

DEFAULT_ROM = Path("E:/Howard/Bizhawk/Pokemon - HeartGold Version (USA).nds")
DEFAULT_SAVE = Path("E:/Howard/Bizhawk/NDS/SaveRAM/Pokemon - HeartGold Version (USA).SaveRAM")
DEFAULT_PRET = Path("E:/Howard/hgss_archipelago-master/.tooling/pokeheartgold")
HGE_SAVE = lane_root() / "saves" / "hge_a_OOO_630.SaveRAM"  # owner hge save: Cyndaquil L5, OOO

# Per-title save Location: the pack's profile.location names array 5's general-block offset
# (HG 0x1234, hge 0x1424: hge's earlier arrays are larger) and the Location field offsets. The
# save image carries no array-header table (it lives in the in-RAM SaveData), so the pack's
# FILE-checked `general_off_of_array` is the source; plan_route's matrix map-id check refuses a
# wrong one. game -> (pack profile.json, title key, codec profile, default ROM/save/lane/tag)
HGE_ROM = REPO / ".cache/gen4/hge/build-fc5175764983/test.nds"
GAMES = {
    "HG": (REPO / "data/games/gen4_hgss/profile.json", "heartgold", "hgss"),
    "hge": (REPO / "data/games/gen4_hge/profile.json", "heartgold_hge", "hge"),
    # SoulSilver (sha1 f8dc38ea, data/gen4_sources.lock.json): the same HGSS pack, its own title. The
    # matrix, land-data and zone-event NARCs are byte-identical to HG's (a unit test pins the hashes),
    # so the pret events are reused; same symbols, same Location offset.
    "SS": (REPO / "data/games/gen4_hgss/profile.json", "soulsilver", "hgss"),
}
SS_ROM = Path("E:/Howard/hgss_archipelago-master/Pokemon - SoulSilver Version (USA).nds")
SS_SAVE = lane_root() / "saves" / "ss_DDDD_25944.SaveRAM"  # owner SS save: Totodile L5, DDDD
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


GRASS_COST = 12  # extra step cost on encounter grass for walks that must NOT fight (the PC route)


def _search(
    world: World, start: tuple[int, int], goal_ok, limit: int = 600_000, grass_cost: int = 0
):
    """Dijkstra (unit steps, SOFT_COST extra on a coord-event tile, `grass_cost` extra on
    encounter grass): cheapest path to a goal."""
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
                if grass_cost and world.is_grass(*nxt):
                    c += grass_cost
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
ERRANDS = {
    "pokegear": ("MAP_NEW_BARK_PLAYER_HOUSE_1F", "obj_T20R0201_gsmama"),
    # the Cherrygrove Pokemon Center PC (G1 row i / the `pc` phase): the "NPC" is the PC TILE, the
    # one tile of behaviour 0x83 in the interior's land data (see load_errand / plan_pc)
    "cherrygrove_pc": ("MAP_CHERRYGROVE_POKECENTER_1F", ("tile", 0x83)),
}
ERRAND_PHASES = ("enter", "talk", "exit")
CHERRYGROVE_ID = 67  # MAP_CHERRYGROVE (include/constants/maps.h:71)
# The PC is a METATILE script, not a bg event: GetInteractedMetatileScript
# (asm/overlay_01_021E6880.s:1466-1700) returns std_pokecenter_pc (2010,
# include/constants/std_script.h:23) when the tile in FRONT of the player has behaviour
# TILE_BEHAVIOR_131 == 0x83 (sub_0205B7E0, src/metatile_behavior.c:91-93; enum position 131,
# include/constants/metatile_behavior.h) AND the player faces north (the `cmp r6, #0` at
# 0x021E7458: PlayerAvatar_GetFacingDirection == 0). The interior's bg event at (4,8) is a decoy.
PC_FACE = "Up"
PC_BEHAVIOR = 0x83

# The PC WITHDRAW leg (box -> party). Every input names its SOURCE (pokeheartgold @ad7a3afa, see
# docs/gen4/G2_PRODUCER_PLAN.md "6b CORRECTION 3"); `inferred` marks a step with no source line, which the
# Lua polls by a RAM signal instead of trusting. A full party is refused by the source itself
# (ov14_021F13B0, :23513-23514 takes a branch that never schedules the commit), and the leg
# refuses it by name before any input, because the run's SYNTH fixture must have room.
WITHDRAW_CELL = 0  # box cell 0 = box slot 0 (cells 0x00-0x1D box grid, 0x1E-0x23 party; data+0x21 is the cached selection byte, see below)
# Opcode 752 MenuExec uses ov27's touchscreen grid (NOT opcode 67's 2D menu).
# scrcmd_c.c:5025-5032 -> ov01_021F6ABC(fs,3,7,p_ret); overlay_27.s
# ov27_0225CA68 indexes the neighbor tables by count-2. For 5/6 items, index0
# Right=1 (WITHDRAW), Down=2 (MOVE): ov27_0225D174 / ov27_0225D1B4.
WITHDRAW_MENU_KEY = "Right"
WITHDRAW_MENU_STEPS = 1
WITHDRAW_MENU_HOLD = 3  # restore original hold; the issue was grid navigation
# Read-only PC diagnostic facts, pokeheartgold@ad7a3afa. The root pointer is
# RAM.fieldsys from the title pack; these are structure offsets, never addresses.
# src/fieldmap.c:327-331 and src/task.c:122-124 -> task.env, magic guard;
# :351-361 and include/constants/vars.h -> special var 0x800C (u16).
# xMAP FieldSysGetAttrAddrInternal returns env+0x8C+(field-42)*2;
# VAR_SPECIAL_RESULT index 12 therefore lives at +0xA4. RUNNING_APP_DATA = +0xAC.
# ScrCmd_158 (src/scrcmd_c.c:1986-1994), inline PCBoxAppData_New
# (include/launch_application.h:97-103) stores ScriptReadByte into PCBoxArgs.unk8;
# OverlayManager_GetArgs (src/overlay_manager.c:46-48) gives man+0x18 -> args+8.
# FILE proofs check these xMAP functions against HG, SS and hge ARM9 bytes.
WITHDRAW_WITNESS = {
    "schema": "gen4-pc-witness-v1", "fs_task_off": 0x10,
    "task_prev_off": 0, "task_env_off": 0xC, "env_magic": 222271,
    "special_var_id": 0x800C, "env_result_off": 0xA4, "env_app_args_off": 0xAC,
    "fs_sub_off": 0, "sub_manager_off": 4, "manager_overlay_off": 0xC,
    "manager_args_off": 0x18, "args_mode_off": 8,
    "source_symbols": ["FieldSysGetAttrAddrInternal", "FieldSysGetAttrAddr",
                       "TaskManager_GetEnvironment", "GetVarPointer", "ScrCmd_158",
                       "PCBox_LaunchApp", "OverlayManager_GetArgs"],
}
WITHDRAW_PARTY_MAX = 5  # a party of 6 has no room
# SOURCE: THREE accepted A presses after interact: dismiss msg33's \r, select
# Which-PC row0 (Someone/Bill), dismiss msg35's \r. Then Right selects WITHDRAW
# in the DIFFERENT storage menu. scr_seq_0003.s:754-838; msg_0040.gmm:142-152;
# scrcmd_message.c:142-151; render_text.c:270-273,302-310,512-519.
# {YESNO 0} in msg34 draws a focus indicator, NOT a blocking YesNo question:
# charmap.txt:2889 and render_text.c:158-168. MenuInit cursor0: scrcmd_c.c:988-997.
# A during printing only speeds printing (render_text.c:95-105), and cannot also
# satisfy the later \r/menu. Replay wd-hg-1003033806 showed this failure. Waits the
# existing 900-frame bound before each semantic A, not extra
# A-mash (which would choose DEPOSIT once the storage menu is reached).
# _0C01 returns via NonNPCMsg (instant print, no \r in msg34) straight to _0B53:
# scr_seq_0003.s:879-885; scrcmd_message.c:45-50,226-232. Thus recover_a=0.
WITHDRAW_SCRIPT_A = 3
WITHDRAW_RECOVER_A = 0
WITHDRAW_A_PERIOD = 120
WITHDRAW_MENU_ATTEMPTS = 3
WITHDRAW_LAUNCH_WAIT = 900  # frames to wait for the app after the sub-menu A (a real launch is ~500)
# KEYBOARD box-mon menu, pokeheartgold@ad7a3afa. The FIRST A at idle 0x51 on an occupied BOX
# cell (cell < 0x1E) does NOT transfer: ov14_021EDA4C's button branch falls into _021EDDC4
# (asm/overlay_14.s:16968-16999), which builds the 4-item action menu and parks
# GridInputHandler.nextInput on the first party-band cell, 0x22, then calls ov14_021F04D4 ->
# state 0x58. The descriptor ov14_021F7D2C (:36938-36940) is 0x45 WITHDRAW / 0x41 SUMMARY /
# 0x43 MARKING / 0x44 RELEASE, WITHDRAW FIRST; msg_0024 ids 69/65/67/68. State 0x58
# (ov14_021EE850, :18286-18295) frees the heap block and RETURNS 0x51, so the settled witnesses
# are nextInput (data+0x34 -> work+0x2C -> grid+0x0D) == 0x22, the selected-cell byte
# data+0x21 == the cursor cell, and work+4 == 0 (the generic async wait reads that same flag:
# ov14_021EB1C0, :11619-11622, dispatching the deferred handler at data+0x30).
WITHDRAW_CONTEXT_TARGET = 0x22
WITHDRAW_CONTEXT_SELECT_KEY = "A"
WITHDRAW_CONTEXT_SELECT_COUNT = 1
# The commit continuation is 0x55, NOT the 0x57 the plan used to name. 0x57 is the TOUCH grab:
# ov14_021F0418 (:21594-21677) is reached only from the branch at :16575-16618, whose cell comes
# from ov14_021F6A14 = TouchscreenHitbox_FindRectAtTouchNew (:34563-34565), and it schedules 0x57
# at :21672. A keyboard leg never samples it, so nothing may oracle on it.
WITHDRAW_COMMIT_STATE = 0x55
WITHDRAW_STEPS = (
    {"step": "interact", "press": "A", "inferred": False,
     "source": "GetInteractedMetatileScript -> std_pokecenter_pc, scr_seq_0003.s:754-762 (scr_seq_0003_010)"},
    {"step": "script_a", "press": "A", "count": WITHDRAW_SCRIPT_A, "inferred": True,
     "source": "scr_seq_0003.s:754-838; msg_0040.gmm:142-152; render_text.c:95-105,270-273,302-310: "
               "three ACCEPTED A: msg33 carriage wait / choose storage row0 / msg35 carriage wait; "
               "existing launch_wait bounds each printer wait (timing unmeasured)"},
    {"step": "menu_move", "press": WITHDRAW_MENU_KEY, "inferred": False,
     "source": "scrcmd_c.c:5025-5032 (opcode752); overlay_27.s:5414-5445,5540-5648,6163-6175; "
               "index0 Right=1 WITHDRAW, Down=2 MOVE; scr_seq_0003.s:821-827 item values"},
    {"step": "menu_withdraw", "press": "A", "inferred": False,
     "source": "scr_seq_0003.s:834-846 (_0B53 Case 1 -> _0BB5), :851-856 ScrCmd_158 1 -> PCBox_LaunchApp mode 1"},
    {"step": "app_state_0x51", "wait_state": 0x51, "inferred": False,
     "source": "asm/overlay_14.s:11822-11831 (ov14_021EB2EC, table entry 0xB :36977): mode 1 -> next state 0x51, "
               "cursor cell 0 (ov14_021E7588); mode 0 -> 0x5B (a 0x5B here means the DEPOSIT row was taken)"},
    {"step": "cursor_on_cell", "cell": WITHDRAW_CELL, "inferred": False,
     "source": "asm/overlay_14.s:11824-11826 (cursor set to cell 0 on entry); data+0x21 is read back, not driven"},
    {"step": "select_box_mon", "press": "A", "count": 1, "inferred": False,
     "source": "idle 0x51 with the cursor on an occupied BOX cell (<0x1E): ov14_021EDA4C falls into "
               "_021EDDC4 (asm/overlay_14.s:16968-16999), which builds the action menu "
               "ov14_021F7D2C (:36938-36940 = 0x45 WITHDRAW, 0x41 SUMMARY, 0x43 MARKING, 0x44 "
               "RELEASE; WITHDRAW FIRST), parks nextInput on 0x22 and calls ov14_021F04D4. The mon is "
               "NOT transferred and the party is untouched: this A only opens the menu"},
    {"step": "menu_context", "wait_cursor": WITHDRAW_CONTEXT_TARGET, "inferred": False,
     "source": "state 0x58 (ov14_021EE850, asm/overlay_14.s:18286-18295) frees the heap block and "
               "returns 0x51; settled when nextInput == 0x22, data+0x21 == the cursor cell and "
               "work+4 == 0 (the async-callback flag ov14_021EB1C0, :11619-11622, waits on before "
               "dispatching data+0x30). A cursor on 0x23/0x24/0x25 is another menu row, not WITHDRAW"},
    {"step": "select_withdraw", "press": WITHDRAW_CONTEXT_SELECT_KEY,
     "count": WITHDRAW_CONTEXT_SELECT_COUNT, "inferred": False,
     "source": "the SECOND fresh A at nextInput 0x22 is case 4 of the 0x1E-base jump table (r5 = "
               "0x22 - 0x1E), _021EDB98 (asm/overlay_14.s:16697-16706,16730-16746): Party_GetCount "
               "chooses the sound, then ov14_021F2270(data, 4, 0xA7) -- highlight wait returning "
               "state 8 with data+0x30 = 0xA7 (:25375-25378). No third A exists on this path"},
    {"step": "commit", "wait_party_delta": 1, "state": WITHDRAW_COMMIT_STATE, "inferred": False,
     "source": "0xA7 -> ov14_021F27CC -> ov14_021F13B0 (:23511-23528): a party of 6 takes the "
               "refusal branch and never reaches the commit; otherwise state 0x53 "
               "(ov14_021EDE38, :17037-17044) -> 0x54 (:17055-17058) -> 0x55 (ov14_021EDE88, "
               ":17064-17119), whose ov14_021E637C (:17100) reaches ov14_021E6184 (:1113-1119): "
               "Party_AddMon then PCStorage_DeleteBoxMonByIndexPair. NO further input; oracled by "
               "the party delta, the appended key and the cleared box slot, 0x55 is only logged. "
               "0x57 is the TOUCH grab (ov14_021F0418, :21672) and is never sampled"},
    {"step": "grid_restored", "wait_state": 0x51, "inferred": True,
     "source": "0x55 hands over to the 0x56 continuation (:17110-17113) and the box grid comes back "
               "to 0x51; the live timing is not measured -- logged, never required"},
    {"step": "exit_app", "press": "B", "inferred": True,
     "source": "B at 0x51 is INFERRED to reach the 'Continue Box operations?' YesNo (state 0x94, B = No) "
               "the deposit leg exits through; the leg re-presses B until the overlay is gone"},
    {"step": "save", "legs": "persistence", "inferred": False,
     "source": "the same native SAVE legs as the deposit (pack route_legs)"},
)


@dataclass
class Errand:
    house_id: int
    outer_id: int
    house: World  # the interior (local coordinates)
    door_out: tuple[int, int]  # the outdoor warp tile into the house
    door_in: tuple[int, int]  # the interior warp tile back out
    npc: tuple[int, int]  # the NPC tile (pokegear) or the PC tile (cherrygrove_pc)


def _bank_json(pret: Path, bank: int) -> list[dict]:
    edir = _need(pret / "files/fielddata/eventdata/zone_event", "zone_event json dir")
    return [
        json.loads(f.read_text(encoding="utf-8")) for f in sorted(edir.glob(f"{bank:03d}_*.json"))
    ]


def _map_ids(pret: Path) -> dict[str, int]:
    return {
        n: int(v)
        for n, v in re.findall(
            r"#define (MAP_\w+)\s+(\d+)",
            _need(Path(pret) / "include/constants/maps.h", "maps.h").read_text(encoding="utf-8"),
        )
    }


def load_errand(rom_path, pret, name: str, outer_id: int) -> Errand:
    if name not in ERRANDS:
        raise RouteError("unknown_errand", f"{name!r} is not one of {sorted(ERRANDS)}")
    house_const, npc_spec = ERRANDS[name]
    pret = Path(pret)
    ids = _map_ids(pret)
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
    if isinstance(npc_spec, tuple):  # ("tile", behaviour): the unique tile of that behaviour
        npc = [
            (x, z)
            for z in range(CELL)
            for x in range(CELL)
            if (house.attr(x, z) or 0) & 0xFF == npc_spec[1]
        ]
    else:
        npc = [(o["x"], o["z"]) for d in inner for o in d.get("objects", []) if o["id"] == npc_spec]
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


def _walk_extras(world: World, path: list[tuple[int, int]]) -> dict:
    """What a long walk can run into, for the Lua harness: grass tiles (a wild encounter can fire
    on each) and coord-event tiles (a cutscene may fire) -- same fields as plan_route."""
    return {
        "approach_grass": [list(t) for t in path if world.is_grass(*t)],
        "soft_events": [
            {"x": t[0], "y": t[1], "scriptIds": list(world.coord_scripts.get(t, ()))}
            for t in path
            if t in world.soft
        ],
    }


def _check_start(w: World, start: dict) -> tuple[int, int]:
    sx, sy = start["x"], start["y"]
    actual = w.map_at(sx, sy)
    if actual != start["map"]:
        raise RouteError(
            "map_mismatch", f"start map {start['map']} but ({sx},{sy}) is in map {actual}"
        )
    return sx, sy


def plan_errand(world: World, errand: Errand, phase: str, start: dict, game: str = "HG") -> dict:
    """One errand leg from `start`: enter (outdoors -> door), talk (house -> beside Mom, facing
    her), exit (house -> door). The tile in front of a door/NPC is the goal; the door step is
    flagged `warp` and the NPC turn is `talk.face`. Encounter grass is priced (GRASS_COST), not
    forbidden: the Route 29 corridor to Cherrygrove has 32 grass tiles no path avoids."""
    if phase not in ERRAND_PHASES:
        raise RouteError("unknown_phase", phase)
    if phase == "enter":
        w, target, dest = world, errand.door_out, errand.house_id
    else:
        w, target, dest = errand.house, errand.npc if phase == "talk" else errand.door_in, None
    sx, sy = _check_start(w, start)
    free = replace(w, blocked=w.blocked - {(sx, sy)})
    path = _search(
        free,
        (sx, sy),
        lambda t: abs(t[0] - target[0]) + abs(t[1] - target[1]) == 1,
        SEARCH_LIMIT,
        GRASS_COST,
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
        **_walk_extras(w, path),
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


def plan_pc(errand: Errand, start: dict, game: str = "HG", phase: str = "deposit") -> dict:
    """The interior leg of the PC stop: from `start` (the arrival tile the previous leg logged)
    to the tile SOUTH of the PC, which is where the player must stand to face it north (PC_FACE;
    see PC_BEHAVIOR). The leg ends facing the PC; the Lua then runs `phase` ("deposit", or
    "withdraw" which also carries the box-withdraw input plan, WITHDRAW_STEPS)."""
    if phase not in ("deposit", "withdraw"):
        raise RouteError("unknown_pc_phase", f"{phase!r} is not deposit or withdraw")
    w = errand.house
    sx, sy = _check_start(w, start)
    stand = (errand.npc[0], errand.npc[1] + 1)
    if not (w.walkable(*stand) or stand == (sx, sy)):
        raise RouteError("pc_data", f"the tile south of the PC {errand.npc} is not walkable")
    free = replace(w, blocked=w.blocked - {(sx, sy)})
    path = _search(free, (sx, sy), lambda t: t == stand, SEARCH_LIMIT, GRASS_COST)
    if not path:
        raise RouteError("no_path", f"pc: no walkable path from ({sx},{sy}) to {stand}")
    return {
        "version": 1,
        "game": game,
        "kind": "pc",
        "phase": phase,
        "start": {**_loc(w, (sx, sy)), "dir": start.get("dir")},
        "steps": _runs(w, path),
        "tiles": len(path) - 1,
        "pc": {
            "x": errand.npc[0],
            "y": errand.npc[1],
            "stand": list(stand),
            "face": PC_FACE,
            **({"withdraw": withdraw_plan()} if phase == "withdraw" else {}),
        },
        "approach_grass": [],
        "soft_events": [],
    }


def withdraw_plan() -> dict:
    """The box-withdraw inputs the Lua leg follows: the ordered, source-cited steps plus the numbers
    it drives (menu rows to go down, the box cell to select, the cursor the action menu parks on)."""
    return {
        "menu_steps": WITHDRAW_MENU_STEPS,
        "menu_key": WITHDRAW_MENU_KEY,
        "menu_hold": WITHDRAW_MENU_HOLD,
        "witness": {**WITHDRAW_WITNESS, "source_symbols": list(WITHDRAW_WITNESS["source_symbols"])},
        # ov14_021EDA4C / ov14_021F6E8C -> GridInputHandler_GetNextInput.
        # data+0x21 is the cached selection byte (written by ov14_021F04D4, :21583-21585), NOT the
        # button cursor target; work+4 is the async-callback flag ov14_021EB1C0 waits on.
        "cursor": {"data_work_off": 0x34, "work_grid_off": 0x2C,
                   "target_off": 0xD, "buttons_off": 8, "work_busy_off": 4, "selected_off": 0x21,
                   "source": "asm/overlay_14.s:16573-16665,16968-16999,35157-35232; "
                             "src/unk_02019BA4.c:121-128,177-184,226-228"},
        "box_cell": WITHDRAW_CELL,
        "context_target": WITHDRAW_CONTEXT_TARGET,
        "context_select_key": WITHDRAW_CONTEXT_SELECT_KEY,
        "context_select_count": WITHDRAW_CONTEXT_SELECT_COUNT,
        "commit_state": WITHDRAW_COMMIT_STATE,
        "party_max": WITHDRAW_PARTY_MAX,
        "script_a": WITHDRAW_SCRIPT_A,
        "script_wait": WITHDRAW_LAUNCH_WAIT,
        "recover_a": WITHDRAW_RECOVER_A,
        "a_period": WITHDRAW_A_PERIOD,
        "menu_attempts": WITHDRAW_MENU_ATTEMPTS,
        "launch_wait": WITHDRAW_LAUNCH_WAIT,
        "steps": [dict(s) for s in WITHDRAW_STEPS],
    }


PACE_NEIGHBOURS = ("Left", "Right", "Down", "Up")


def plan_hatch(world: World, start: dict, game: str = "HG", max_steps: int = 700) -> dict:
    """Walk back and forth between the start tile and a neighbour until the egg hatches (a step
    counter reaches an egg-cycle boundary every 255 steps, src/get_egg.c:763-809). Both tiles must be
    plain floor: walkable, not encounter grass, not a coord-event tile, not a warp, and not Surf
    water -- so no encounter or cutscene can interrupt the count. The neighbour is the first of
    PACE_NEIGHBOURS that qualifies."""
    sx, sy = start["x"], start["y"]
    actual = world.map_at(sx, sy)
    if actual != start["map"]:
        raise RouteError(
            "map_mismatch", f"save says map {start['map']} but ({sx},{sy}) is in map {actual}"
        )

    def plain(t):
        return (
            world.attr(*t) is not None
            and (world.walkable(*t) or t == (sx, sy))
            and not world.is_grass(*t)
            and t not in world.soft
            and t not in world.warps
            and not world.is_water(*t)
        )

    if not plain((sx, sy)):
        raise RouteError("start_not_plain", f"({sx},{sy}) is grass, a coord tile or a warp")
    for d in PACE_NEIGHBOURS:
        n = (sx + DIRS[d][0], sy + DIRS[d][1])
        if plain(n):
            return {
                "version": 1,
                "game": game,
                "kind": "hatch",
                "phase": "hatch",
                "start": {**_loc(world, (sx, sy)), "dir": start.get("dir")},
                "steps": [],
                "tiles": 0,
                "pace": {
                    "a": [sx, sy],
                    "b": list(n),
                    "dir_ab": d,
                    "dir_ba": _dir_of(n, (sx, sy)),
                    "max_steps": max_steps,
                },
            }
    raise RouteError("no_pace_tile", f"no plain neighbour of ({sx},{sy})")


def plan_pc_stop(rom, pret, world: World, start: dict, game: str = "HG", phase: str = "deposit") -> dict:
    """The whole PC stop planned offline: the outdoor walk to the Pokemon Center door, and the
    interior walk to the PC tile assuming the player arrives ON the interior warp tile facing up
    (the live run re-plans the second leg from the arrival tile the first one logs). A `start`
    already inside the Pokemon Center (a save made at the PC) plans only the interior leg."""
    pc = load_errand(rom, pret, "cherrygrove_pc", CHERRYGROVE_ID)
    if start["map"] == pc.house_id:
        return {phase: plan_pc(pc, start, game, phase)}
    arrive = {"map": pc.house_id, "x": pc.door_in[0], "y": pc.door_in[1], "dir": 0}
    return {
        "enter": plan_errand(world, pc, "enter", start, game),
        phase: plan_pc(pc, arrive, game, phase),
    }


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


# --- pack-derived inputs for the PC stop ----------------------------------------------------------
# The Lua harness reads no constant the pack already records: the button-recipe legs (battle escape,
# native SAVE) and the RAM layout (SaveArray headers, PCStorage, Party) travel in the route JSON.
PC_LEGS = ("run_from_wild",)
SAVE_LEGS = (
    "open_start_menu",
    "start_menu_cursor_to_save",
    "start_menu_select_save",
    "save_confirm_until_saved",
    "close_start_menu",
)


def _pack_title(game: str) -> dict:
    if game not in GAMES:
        raise RouteError("unknown_game", f"{game!r} is not one of {sorted(GAMES)}")
    path, title, _ = GAMES[game]
    return json.loads(_need(path, f"{game} pack").read_text(encoding="utf-8"))["titles"][title]


def pack_legs(game: str, names) -> dict:
    """titles.<t>.route_legs[name] with `until.symbol` resolved to its address. An OPEN leg is
    refused by name: a recipe the pack cannot back is never replayed."""
    t = _pack_title(game)
    out = {}
    for n in names:
        leg = t["route_legs"].get(n)
        if leg is None or leg.get("route_status") != "recipe_source":
            raise RouteError("leg_open", f"{game} pack leg {n!r}: {(leg or {}).get('open')}")
        u = leg["until"]
        out[n] = {
            "steps": leg["steps"],
            "max_frames": leg["max_frames"],
            "until": {**u, "address": t["symbols"][u["symbol"]]["address"]},
        }
    return out


def pack_ram(game: str) -> dict:
    """The RAM layout the PC leg reads (all from the pack): SaveArray header geometry, the party
    and PCStorage arrays, the probe_field offsets. hge records no box-modified offset (null)."""
    t = _pack_title(game)
    pr = t["profile"]
    sv, pc, po = pr["save"], pr["pc"], pr["party_off"]
    return {
        "fieldsys": t["symbols"]["sFieldSysPtr"]["address"],
        "save_ptr": pr["save_ptr"]["address"],
        "hdr_off": sv["array_headers_off"],
        "hdr_size": sv["array_header_size"],
        "hdr_offset_field": sv["array_header_fields"]["offset"],
        "hdr_size_field": sv["array_header_fields"]["size"],
        "dyn_off": sv["dynamic_region_off"],
        "id_party": sv["array_ids"]["party"],
        "id_pc": sv["array_ids"]["pcstorage"],
        "party": {
            "count_off": po["count_off"],
            "mons_off": po["mons_off"],
            "size": pr["pkm"]["party_size"],
        },
        "pc": {
            "boxes": pr["boxes"],
            "per_box": pr["mons_per_box"],
            "box_base": pc["box_base"],
            "box_stride": pc["box_stride"],
            "mon_stride": pc["mon_stride"],
            "cur_box_off": pc["cur_box_off"],
            "mod_off": pc["box_modified_flag_off"],
        },
        "field": pr["probe_field"],
    }


def pack_profile_slice(game: str) -> dict:
    """The pack profile sections lua/gen4/reads.lua party() needs (a trimmed copy: the full
    profile carries long evidence tables the harness never reads)."""
    pr = _pack_title(game)["profile"]
    return {k: pr[k] for k in ("save", "save_ptr", "party_off", "pkm")}


BRIDGE_LEGS = {"gen4_routes:battle_settled", "gen4_pc:reach_pc_terminal", "boot_continue_to_overworld"}


class BridgePlanner:
    """The probe requests routes from its CURRENT RAM position, using the existing C1-9 planner.

    A PC bridge executes the proven enter/deposit/SAVE/exit cycle. Withdrawal is
    still outside that engine's capabilities and must remain explicitly OPEN.
    No state load or game-data mutation occurs at a bridge boundary.
    """
    def __init__(self, rom, game, synth=None, pret=DEFAULT_PRET):
        self.rom, self.game, self.pret, self.synth = rom, game, pret, synth
        self.world = None
        self.pc = None
        self.gate = None  # (map, x) of the T20_002 coord event the last battle plan crossed
        self.pokegear = None  # the errand once the gate is live
        self.phase = None  # the errand leg last sent: enter / talk / exit / done

    def _pokegear_errand(self, position):
        """The Pokegear errand leg for this request, or None to plan the normal route. The coord
        event T20_002 walks a save with no Pokegear back east of it on every pass: a request that
        returns to the same map still east of the event proves the gate is live (run_lane's
        `--errand pokegear`, enter -> talk -> exit, each leg re-planned from the logged position)."""
        here = self.pokegear is not None and position["map"] == self.pokegear.house_id
        if self.phase == "done" and position["map"] == self.armed[0] and position["x"] > self.armed[1]:
            self.phase = None  # walked back again: the talk did not take (adjacency is not proof); re-arm
            self.gate = self.armed
        if self.phase is None:
            if self.gate is None or position["map"] != self.gate[0] or position["x"] <= self.gate[1]:
                return None
            self.pokegear = load_errand(self.rom, self.pret, "pokegear", position["map"])
            self.armed = self.gate
            self.phase = "enter"
        elif self.phase == "enter" and here:
            self.phase = "talk"
        elif self.phase == "talk" and here and (
            abs(position["x"] - self.pokegear.npc[0]) + abs(position["y"] - self.pokegear.npc[1]) == 1
        ):
            self.phase = "exit"  # beside Mom: the talk leg ran
        elif self.phase == "exit" and not here:
            self.phase = "done"
        if self.phase == "done":
            return None
        return plan_errand(self.world, self.pokegear, self.phase, position, self.game)

    def plan(self, request):
        name, position = request["leg"], request["position"]
        if name not in BRIDGE_LEGS or name == "boot_continue_to_overworld":
            raise RouteError("unsupported_bridge", name)
        if self.world is None:
            self.world = load_world(self.rom, self.pret)
        if name == "gen4_routes:battle_settled":
            errand = self._pokegear_errand(position)
            if errand:
                return errand
            return self._track_gate(position, plan_route(self.world, position, wild_land_day(Path(self.pret)), self.game))
        if self.synth is None:
            raise RomAbsent("OPEN PC bridge requires a disclosed SYNTH party2 input")
        if self.pc is None:
            self.pc = load_errand(self.rom, self.pret, "cherrygrove_pc", CHERRYGROVE_ID)
        extra = {"run_from_wild": pack_legs(self.game, PC_LEGS)["run_from_wild"],
                 "persistence": pack_legs(self.game, SAVE_LEGS), "ram": pack_ram(self.game),
                 "synth": self.synth, "profile": pack_profile_slice(self.game)}
        if position["map"] == self.pc.house_id:
            return {**plan_pc(self.pc, position, self.game), **extra}
        errand = self._pokegear_errand(position)  # the walk to Cherrygrove crosses the same gate
        if errand:
            return {**errand, **extra}
        return {**self._track_gate(position, plan_errand(self.world, self.pc, "enter", position, self.game)), **extra}

    def _track_gate(self, position, plan):
        """Remember the T20_002 coord event this plan crosses (the Pokegear gate), else None."""
        self.gate = next(
            (
                (position["map"], e["x"])
                for e in plan.get("soft_events", ())
                if any("T20_002" in sid for sid in e["scriptIds"])
            ),
            None,
        )
        return plan


SYNTH_SCHEMA = "gen4-synth-v1"
# run_lane PC targets -> (SYNTH kind of the input save, the passing Lua status, the plan_pc phase)
PC_TARGETS = {
    "pc": ("party2", "PC_DEPOSIT", "deposit"),
    "pc_withdraw": ("party2", "PC_WITHDRAW", "withdraw"),
}


def synth_setup(save, kind: str = "party2") -> dict:
    """The disclosed SYNTH setup behind a party-2 save (tools/gen4_synth_save.py): its sidecar
    `<save>.synth.json` must exist and describe THIS file. Every receipt carries `setup: SYNTH` and
    the sidecar hash; a one-mon save cannot deposit (Gen 4 refuses the last party mon), so a
    missing sidecar is a named refusal, not a run that fails later in the UI."""
    sidecar = Path(str(save) + ".synth.json")
    if not sidecar.is_file():
        raise RouteError(
            "setup_missing",
            f"no {sidecar.name}: run tools/gen4_synth_save.py party2 --src <battery> --out {save}",
        )
    raw = sidecar.read_bytes()
    row = json.loads(raw)
    if row.get("schema") != SYNTH_SCHEMA or row.get("kind") != kind:
        raise RouteError(
            "setup_mismatch", f"{sidecar.name}: schema/kind {row.get('schema')}/{row.get('kind')}"
        )
    if row.get("out_sha1") != sha1_of(Path(save)):
        raise RouteError("setup_mismatch", f"{sidecar.name} does not describe {Path(save).name}")
    return {
        "setup": "SYNTH",
        "sidecar": sidecar.name,
        "sidecar_sha256": hashlib.sha256(raw).hexdigest(),
        "new_pid": row["new_pid"],
        "otid": row["otid"],
        "out_sha1": row["out_sha1"],
        "kind": kind,
        "species": row.get("species"),
    }


def verify_saved_hatch(path, game: str, synth: dict) -> dict:
    """The battery after the hatch + SAVE: the SYNTH egg's key is party slot 1, no longer an egg."""
    save = parse_save(Path(path).read_bytes(), GAMES[game][2])
    party = save.party()
    key = mon_key(synth["new_pid"], synth["otid"])
    mon = party[1] if len(party) > 1 else None
    if mon is None or mon["key"] != key or mon["is_egg"] or mon["species"] != synth["species"]:
        raise RouteError(
            "saved_mismatch",
            f"saved party slot 1 is {mon and (mon['key'], mon['is_egg'])}, want {key} hatched",
        )
    keep = (
        "species",
        "level",
        "is_egg",
        "met_level",
        "met_location",
        "egg_location",
        "friendship",
        "has_nickname",
    )
    return {"party": len(party), "key": key, **{k: mon[k] for k in keep if k in mon}}


def verify_saved(path, game: str, synth: dict) -> dict:
    """The battery file the run left (BizHawk flushes it on exit), decoded by the codec. The exact
    claim of the PC run: party of ONE mon, the SYNTH clone (key PID:OTID) in box 0 slot 0 and nowhere
    else, and the PCStorage's current box 0 (when the profile records it). Records the battery's own
    boxModifiedFlag word: the saved FILE keeps it set (1) while RAM reads 0 after SAVE and after load,
    so a receipt must not say that SAVE clears the file. Anything else is a named refusal."""
    save = parse_save(Path(path).read_bytes(), GAMES[game][2])
    party = save.party()
    key = mon_key(synth["new_pid"], synth["otid"])
    boxed = [
        (i, slot)
        for i, box in enumerate(save.boxes())
        for slot, mon in box["mons"].items()
        if mon["key"] == key
    ]
    meta = save.pc_meta()
    if len(party) != 1 or boxed != [(0, 0)] or meta.get("cur_box", 0) != 0:
        raise RouteError(
            "saved_mismatch",
            f"saved file: party {len(party)} mons, clone {key} boxed at {boxed} (want [(0, 0)]), "
            f"cur_box {meta.get('cur_box')}",
        )
    return {
        "party": len(party),
        "clone_key": key,
        "box": boxed[0][0],
        "slot": boxed[0][1],
        "cur_box": meta.get("cur_box"),
        "battery_modified": meta.get("modified"),
    }


def withdraw_precondition(before: dict, synth: dict) -> None:
    """Refuse a setup the withdraw leg cannot claim BEFORE any emulator runs: a party with no room
    (the source refuses a full party itself, ov14_021F13B0 :23513-23514, and the leg names it before
    any input), or a SYNTH key that is not alone in box 0 slot WITHDRAW_CELL and absent from the
    party. `before` is save_witness() of the input save."""
    key = mon_key(synth["new_pid"], synth["otid"])
    if len(before["party_keys"]) > WITHDRAW_PARTY_MAX:
        raise RouteError(
            "withdraw_party_full",
            f"party {len(before['party_keys'])}/6: a full party has no room for the clone",
        )
    home = [(b["box"], b["slot"]) for b in before["box_keys"] if b["key"] == key]
    if before.get("cur_box") not in (0, None):  # the grid shows the DISPLAYED box: cell 0 must be box 0's
        raise RouteError("withdraw_setup", f"the displayed box is {before['cur_box']}, not 0")
    if home != [(0, WITHDRAW_CELL)] or key in before["party_keys"]:
        raise RouteError(
            "withdraw_setup",
            f"clone {key} boxed at {home} (want [(0, {WITHDRAW_CELL})]), in party: {key in before['party_keys']}",
        )


def check_withdraw_ram(detail: str) -> dict:
    """Judge the Lua leg's own RAM observation (the `RESULT PC_WITHDRAW` detail, key=value tokens)
    host side: the party grew by one, the source slot is empty, and the box DIRTY MASK has the source
    box's bit CLEAR before the leg and SET after it (a mask, so bit 0 for box 0 -- a non-zero word with
    another bit is a refusal, and a bit that was already set proves nothing). A `nil` mask is the pack
    saying it records no dirty word (hge), never a missing token."""
    obs = dict(t.split("=", 1) for t in detail.split() if "=" in t)
    try:
        before, after = int(obs["party_before"]), int(obs["party_after"])
        box, slot = (int(v) for v in obs["box"].split("/"))
        mod0, mod, saved = obs["mod_before"], obs["mod_after"], obs["mod_saved"]
        slot_after = obs["slot_after"]
    except (KeyError, ValueError) as exc:
        raise RouteError("withdraw_obs", f"unreadable withdraw observation {detail!r}: {exc!r}") from exc
    if after != before + 1:
        raise RouteError("withdraw_party_unchanged", f"party {before} -> {after}, want +1")
    if slot_after != "empty":
        raise RouteError("withdraw_slot_occupied", f"box {box} slot {slot} reads {slot_after}")
    if mod0 != "nil" and int(mod0, 16) & (1 << box):
        raise RouteError("withdraw_dirty_bit", f"dirty mask {mod0} already had bit {box} before the withdraw")
    if mod != "nil" and not int(mod, 16) & (1 << box):
        raise RouteError("withdraw_dirty_bit", f"dirty mask {mod} lacks bit {box} (box {box})")
    if saved != "nil" and int(saved, 16) != 0:
        raise RouteError("withdraw_dirty_not_cleared", f"dirty mask {saved} after the native SAVE")
    return {"party_before": before, "party_after": after, "box": box, "slot": slot, "mod_before": mod0,
            "mod_after": mod, "mod_saved": saved}


def verify_saved_withdraw(path, game: str, synth: dict, before: dict, detail: str) -> dict:
    """The battery after the withdraw + SAVE, decoded by the codec: the party is the input party plus
    the SYNTH key appended, the key is in no box and the source slot is empty. The RAM half
    (check_withdraw_ram) is judged on the same call so one receipt carries both."""
    ram = check_withdraw_ram(detail)
    save = parse_save(Path(path).read_bytes(), GAMES[game][2])
    key = mon_key(synth["new_pid"], synth["otid"])
    # the source cell is the clone's position in the INPUT witness; the cell the Lua reported must agree
    # with it, so a wrong report can never point the file check at an empty box
    home = [(b["box"], b["slot"]) for b in before["box_keys"] if b["key"] == key]
    if home != [(ram["box"], ram["slot"])]:
        raise RouteError(
            "saved_mismatch", f"the Lua reported cell {ram['box']}/{ram['slot']}, the input witness has {home}"
        )
    hb, hs = home[0]
    party = [mon["key"] for mon in save.party()]
    boxes = save.boxes()
    boxed = [(i, s) for i, box in enumerate(boxes) for s, mon in box["mons"].items() if mon["key"] == key]
    if party != before["party_keys"] + [key] or boxed or hs in boxes[hb]["mons"]:
        raise RouteError(
            "saved_mismatch",
            f"saved file: party {party} (want {before['party_keys']} + [{key}]), clone boxed at {boxed}, "
            f"slot {hb}/{hs} occupied: {hs in boxes[hb]['mons']}",
        )
    meta = save.pc_meta()
    return {"op": "withdraw", "party": len(party), "clone_key": key, "party_slot": len(party) - 1,
            "box": ram["box"], "slot": ram["slot"], "cur_box": meta.get("cur_box"),
            "battery_modified": meta.get("modified"), "ram": ram}


def save_witness(path, game) -> dict:
    """Independent FILE oracle: newest coherent bank, wrap-aware counter, exact mon keys."""
    decoded = parse_save(Path(path).read_bytes(), GAMES[game][2])
    party = [mon["key"] for mon in decoded.party()]
    boxes = [{"box": box, "slot": slot, "key": mon["key"]}
             for box, data in enumerate(decoded.boxes()) for slot, mon in data["mons"].items()]
    return {"bank": decoded.bank, "counter": decoded.counter, "party_keys": party, "box_keys": boxes,
            "keys": sorted([*party, *(mon["key"] for mon in boxes)]), "fallback": decoded.fallback,
            "cur_box": decoded.pc_meta().get("cur_box")}


def assert_save_progress(before, saved, reloaded):
    # saved vs before is the real native-SAVE evidence; the reloaded clauses compare the battery file with
    # itself (the reload boot leaves it untouched) and only guard against a corrupted record.
    if counter_newer(saved["counter"], before["counter"]) <= 0:
        raise RouteError("save_counter", "native SAVE did not advance the coherent save counter")
    if counter_newer(reloaded["counter"], saved["counter"]) < 0:
        raise RouteError("save_counter", "cold reload regressed the coherent save counter")
    if saved["keys"] != reloaded["keys"]:
        raise RouteError("reload_keys", "cold reload changed persisted mon keys")


# --- receipts bound at CONSUMPTION (same rule as gates.perf_f in tests/live/test_gen4_probe_gates.py) ----
# A receipt is only evidence for the source it ran from: it carries the git HEAD, the sha256 of the Lua
# script that ran and of every Python/Lua module the run read; verify_receipt() refuses (STALE, never PASS)
# a receipt whose HEAD or any hash no longer matches the tree it is consumed against.
BOUND_MODULES = (
    "tools/gen4_routes.py",
    "tools/gen4_fixtures.py",
    "lua/json_codec.lua",
    "lua/gen4/reads.lua",
    "lua/gen4/pk4.lua",
    "lua/nds/pkm45_crypto.lua",
    "server/adapters/gen4_codec.py",
    "data/games/gen4_hgss/profile.json",
    "data/games/gen4_hge/profile.json",
)
# Per receipt kind: the Lua script that must have run, the modules whose hashes MUST be present (a trimmed
# receipt is refused), and the statuses that count as a pass. A receipt of one kind never passes as the other.
# `save_pass` are the passing statuses whose evidence is a native SAVE + cold reload; the rest (BATTLE, the
# wild-battle leg) persists nothing and is judged by its own battle witness instead.
RECEIPT_KINDS = {
    "route": {
        "script": "lua/tests/gen4_route_play.lua",
        "modules": BOUND_MODULES,
        "status_key": "final_status",
        "pass": ("BATTLE", "PC_DEPOSIT", "PC_WITHDRAW", "HATCH_OK"),
        "save_pass": ("PC_DEPOSIT", "PC_WITHDRAW", "HATCH_OK"),
    },
    "catch": {
        "script": "lua/tests/probe_gen4_catch.lua",
        "modules": (
            "lua/json_codec.lua",
            "tests/live/test_gen4_catch.py",
            "tools/gen4_routes.py",
            "tools/gen4_fixtures.py",
            "tools/gen4_pins.py",
            "server/adapters/gen4_codec.py",
            "data/games/gen4_hgss/profile.json",
            "data/games/gen4_hge/profile.json",
        ),
        "status_key": "verdict",
        "pass": ("PASS",),
    },
}


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()


def receipt_binding(script=None, extra_modules=(), kind: str = "route", title: str = "heartgold") -> dict:
    """Shared evidence surface, frozen before execution; HEAD is provenance only."""
    binding = gen4_evidence.snapshot(kind, title, repo=REPO)
    if script is not None and Path(script).resolve() != (REPO / binding["script"]).resolve():
        raise gen4_evidence.StaleEvidenceError("STALE script: not the requested receipt kind")
    if set(extra_modules) - set(binding["module_sha256"]):
        raise gen4_evidence.StaleEvidenceError("STALE undeclared extra dependencies: extend the shared kind surface")
    return binding


def verify_receipt(path, kind: str, *, head: str | None = None, want: str | None = None) -> tuple[str, str]:
    """Consume a receipt/verdict JSON of `kind` ("route" | "catch"): (verdict, reason).
    STALE when it is unbound, trimmed (a required module hash absent), names the wrong script for its
    kind, or any of source_head / script_sha256 / module_sha256 differs from the tree now. FAIL when the
    ROM it ran on is not the pinned ROM of its title. Otherwise the receipt's own status for THIS kind
    decides (PASS only for that kind's passing statuses; another kind's status is FAIL). `want` binds a
    route receipt to ONE target status (e.g. "PC_WITHDRAW"): any other passing status is a FAIL, and a
    withdraw must also carry the decoded battery's op == "withdraw" (a deposit never does)."""
    spec = RECEIPT_KINDS[kind]
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    title = doc.get("title")
    pin = gen4_pins.ROM_SPECS.get(title)
    if pin is None:
        return "STALE", f"unsupported title: {title}"
    try:
        gen4_evidence.verify(doc, kind, title, pin[0], repo=REPO)
    except gen4_evidence.StaleEvidenceError as exc:
        return "STALE", str(exc)
    status = doc.get(spec["status_key"])
    if want is not None and status in spec["pass"]:
        op = (doc.get("battery") or {}).get("op")
        if status != want or (op == "withdraw") != (want == "PC_WITHDRAW"):
            return "FAIL", f"receipt status {status} (battery op {op}) is not the wanted {want}"
    if status in spec["pass"]:
        if kind == "route":
            if status in spec.get("save_pass", spec["pass"]):
                try:
                    assert_save_progress(doc["before_save"], doc["battery"], doc["reload"]["witness"])
                except (KeyError, TypeError):
                    return "STALE", "missing independent counter/key witnesses"
                except RouteError as exc:
                    return "FAIL", str(exc)
            else:  # BATTLE persists nothing: the leg's own bindings are the evidence instead
                gap = battle_receipt_gap(doc)
                if gap:
                    return "STALE", gap
                witness = doc["battle"]["witness"]
                if not witness["entered"]:
                    return "FAIL", witness["reason"] or "the leg recorded no battle witness"
        elif not isinstance(doc.get("battery_mon"), dict) or not {"pid", "species", "key"} <= doc["battery_mon"].keys():
            return "STALE", "missing independently decoded battery_mon"
        return "PASS", "bound to the current evidence surface"
    return ("OPEN" if status == "OPEN" else "FAIL"), f"{kind} receipt status {status}"


# --- the wild-battle leg's witness (no native SAVE: the battle itself is the evidence) ------------------
# `RESULT BATTLE` is written only once `battle()` returned a live chain (overlay 12 and a non-zero enemy
# species at ctx+0x2D40+0xC0 -- lua/tests/gen4_route_play.lua:124-137), so the species the detail names IS
# the entry witness. The frame counts beside it (`paceSteps`, `framesInGrass`) say how long the leg waited,
# never what it saw, and are deliberately not read here.
BATTLE_WITNESS_RE = re.compile(
    r"phase=(?P<phase>\w+) species=(?P<name>[^()\s]+)\((?P<species>-?\d+)\) level=(?P<level>-?\d+)"
    r" player=(?P<player>-?\d+) map=(?P<map>-?\d+) x=(?P<x>-?\d+) y=(?P<y>-?\d+)"
)
SETTLED_STATE_RE = re.compile(r"^.*\bsavestate battle_settled ok (.+)$", re.MULTILINE)


def battle_witness(result: dict) -> dict:
    """Judge the wild-battle leg from what its own RESULT line reported. `entered` is the battle CHAIN
    (a non-zero enemy species and the player's mon, the `battle()` guard), never a frame count: a leg
    that paced 4000 steps and met nothing must not read as a battle."""
    detail = result.get("detail") or ""
    m = BATTLE_WITNESS_RE.search(detail)
    if m is None:
        return {"entered": False,
                "reason": f"leg status {result.get('status')} names no battle chain: {detail!r}"}
    w = m.groupdict()
    entered = int(w["species"]) > 0 and int(w["player"]) > 0
    return {
        "entered": entered,
        "reason": ""
        if entered
        else f"enemy species {w['species']} / player {w['player']} is no live battle chain",
        "phase": w["phase"],
        "species": int(w["species"]),
        "level": int(w["level"]),
        "player": int(w["player"]),
        "map": int(w["map"]),
        "x": int(w["x"]),
        "y": int(w["y"]),
    }


def settled_state(lines) -> dict | None:
    """The `<tag>_leg<N>_battle_settled.State` the Lua leg wrote, hashed. The path comes from the leg's own
    `savestate battle_settled ok` line, so a leg whose `savestate.save` failed is absent here rather than
    guessed at; a state file that is not there hashes to None, which verify_receipt refuses."""
    m = SETTLED_STATE_RE.search("\n".join(lines or ()))
    if m is None:
        return None
    path = Path(m.group(1).strip())
    return {"path": str(path), "sha256": _sha256(path) if path.is_file() else None}


def battle_receipt_gap(doc: dict) -> str | None:
    """The bindings a wild-battle receipt must carry: the staged battery it ran from, the plan it ran and
    the settled state it left. A receipt missing one is trimmed (STALE), never a pass."""
    battle = doc.get("battle")
    if not isinstance(battle, dict):
        return "missing the battle block"
    if not isinstance(battle.get("witness"), dict):
        return "missing the battle witness"
    for what, holder in (
        ("staged battery", doc.get("staged_save")),
        ("plan", doc.get("plan")),
        ("settled battle state", battle.get("settled_state")),
    ):
        if not isinstance(holder, dict) or not isinstance(holder.get("sha256"), str):
            return f"missing the {what} sha256"
    return None


def build_receipt(
    game, save, synth: dict | None, legs: list[dict], final: dict, rom_sha1: str | None = None, *, binding=None
) -> dict:
    """The run's receipt: the setup label + sidecar hash first, then each leg's status line. `synth` is
    None for a leg with no SYNTH fixture behind it (the wild-battle route runs on the owner's own
    battery): that is disclosed NATIVE with no sidecar, never an invented one."""
    setup = synth or {"setup": "NATIVE", "sidecar": None, "sidecar_sha256": None, "out_sha1": None}
    return {
        **(binding or receipt_binding(title=GAMES[game][1])),
        "title": GAMES[game][1],  # the pinned-ROM key (tools/gen4_pins.py ROM_SPECS)
        "rom_sha1": rom_sha1,
        "setup": setup["setup"],
        "sidecar": setup["sidecar"],
        "sidecar_sha256": setup["sidecar_sha256"],
        "save": str(save),
        "save_sha1": setup["out_sha1"],
        # the battery the lane booted from, hashed AS STAGED (the game rewrites the file, so only the
        # stage-time digest names the battery a battle-derived state came from)
        "staged_save": final.get("staged_save"),
        # the route JSON this leg ran, and the settled state the Lua leg wrote for it
        "plan": final.get("plan"),
        "battle": final.get("battle"),
        "game": game,
        "legs": [
            {k: v for k, v in leg.items() if k in ("leg", "kind", "phase", "status", "detail", "pc_witnesses")}
            for leg in legs
        ],
        "final_status": final["status"],
        "final_detail": final["detail"],
        # the battery as the run left it, decoded by the codec (verify_saved / verify_saved_hatch)
        "battery_sha1": final.get("battery_sha1"),
        "before_save": final.get("before_save"),
        "battery": {**(final.get("saved") or {}), **(final.get("save_witness") or {})} or None,
        # the reload leg's own status line, wall time and log (the fresh boot from that battery)
        "reload": {
            k: v
            for k, v in (final.get("reload") or {}).items()
            if k in ("leg", "status", "detail", "wall", "log", "witness")
        }
        or None,
        # R2: RAM and the file differ -- say each, claim neither for the other
        "modified_flag": {
            "ram": f"set by the {(final.get('saved') or {}).get('op', 'deposit')}; 0 after the native SAVE "
            "and after the cold reload (Lua log)",
            "battery": (final.get("saved") or {}).get("battery_modified"),
        }
        if (final.get("saved") or {}).get("clone_key")
        else None,
    }


# --- live run (one EmuHawk per leg, own lane, bounded) ----------------------------------------
EMUHAWK = Path("E:/Howard/Bizhawk/EmuHawk.exe")
LUA = REPO / "lua" / "tests" / "gen4_route_play.lua"


def parse_result(log: str) -> dict:
    """The last `RESULT <status> ...` line of a Lua log -> {status, detail, lines}."""
    res = {"status": "NO_RESULT", "detail": "", "lines": log.splitlines()}
    for ln in res["lines"]:
        witness = re.search(r"PC_WITNESS (\{.*\})$", ln)
        if witness:
            res.setdefault("pc_witnesses", []).append(json.loads(witness.group(1)))
        m = re.search(r"RESULT (\w+)\s*(.*)$", ln)
        if m:
            res["status"], res["detail"] = m.group(1), m.group(2)
    return res


def _cold_reload(rom_staged, ld, tag, leg, game, route, pc_extra, timeout, history) -> dict:
    """One more EmuHawk on the lane's own battery (no savestate): boot, CONTINUE, then the Lua
    `reload` leg confirms by RAM that the party and the boxed clone persisted."""
    rroute = {
        "version": 1,
        "game": game,
        "kind": "reload",
        "phase": "reload",
        "start": route["start"],
        "steps": [],
        "tiles": 0,
        "ram": pc_extra["ram"],
        "synth": pc_extra["synth"],
        "profile": pc_extra["profile"],
        **({"op": "withdraw"} if route.get("phase") == "withdraw" else {}),
    }
    rpath = ld / f"{tag}_reload.json"
    rpath.write_text(json.dumps(rroute, indent=1), encoding="utf-8")
    log = ld / f"{tag}_reload.log"
    log.unlink(missing_ok=True)
    env = dict(
        os.environ,
        G4_REPO=str(REPO).replace("\\", "/"),
        G4_ROUTE=str(rpath).replace("\\", "/"),
        G4_OUT=str(log).replace("\\", "/"),
        G4_LANE=str(ld).replace("\\", "/"),
        G4_TAG=f"{tag}_reload",
        G4_LOAD_STATE="",
    )
    cmd = [str(EMUHAWK), f"--config={ld / 'bizhawk.ini'}", f"--lua={LUA}", str(rom_staged)]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, cwd=str(ld), env=env)
    except FileNotFoundError as exc:
        raise RomAbsent(f"emulator absent: {cmd[0]}") from exc
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        kill_our_emuhawk(ld)
    res = parse_result(log.read_text(encoding="utf-8") if log.exists() else "")
    res.update(
        leg=leg + 1, kind="reload", phase="reload", wall=round(time.time() - t0, 1), log=str(log)
    )
    history.append(res)
    return res


RESYNC_RE = re.compile(r"map=(-?\d+) x=(-?\d+) y=(-?\d+) dir=(-?\d+)(?: done=([01]))? state=(.+)$")


def run_lane(
    rom=DEFAULT_ROM,
    save=DEFAULT_SAVE,
    pret=DEFAULT_PRET,
    *,
    game="HG",
    errand=None,
    target="grass",
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
    visit (see ERRANDS). `target` is "grass" (walk to a wild battle), "pc" (walk to the
    Cherrygrove Pokemon Center PC, deposit party slot 1 from a SYNTH party-2 save, native SAVE) or
    "pc_withdraw" (the same PC, withdraw box 0 slot 0 into a party with room, native SAVE; the input
    is a boxed SYNTH save such as the deposit run's output).
    A leg that ends in a RESYNC with `done=0` was interrupted mid-walk: the same phase is
    re-planned from where it stopped. Returns the last leg's parsed result."""
    if target not in ("grass", "hatch", *PC_TARGETS):
        raise RouteError("unknown_target", f"{target!r} is not grass, pc, pc_withdraw or hatch")
    kind = "egg1" if target == "hatch" else PC_TARGETS[target][0] if target in PC_TARGETS else None
    synth = synth_setup(save, kind) if kind else None  # refuse before touching the lane
    binding = receipt_binding(title=GAMES[game][1])
    before_save = save_witness(save, game) if kind else None
    if target == "pc_withdraw":
        withdraw_precondition(before_save, synth)
    ld = lane_dir(lane)
    ld.mkdir(parents=True, exist_ok=True)
    write_nds_run_config(
        route_pacing(json.loads(BIZHAWK_CONFIG.read_text(encoding="utf-8-sig")),int(os.environ.get("G4_RATE","300"))),
        ld / "bizhawk.ini",
        initial_time=initial_time,
        lane_saveram_dir=ld / "SaveRAM",
    )
    rom_staged = stage_rom(rom, ld)
    rom_sha1 = sha1_of(rom_staged)
    saved_path = stage_save(save, ld, rom_sha1, rom_basename=rom_staged.name)
    # hash the staged battery as the lane received it, BEFORE any leg runs: the game rewrites the file
    # during the run, so only the stage-time digest identifies what a battle state came from
    staged_save = {"path": str(saved_path), "sha256": _sha256(saved_path) if Path(saved_path).is_file() else None}
    world = load_world(rom, pret)
    start = save_position(save, game)
    err = load_errand(rom, pret, errand, start["map"]) if errand else None
    pc = load_errand(rom, pret, "cherrygrove_pc", CHERRYGROVE_ID) if target in PC_TARGETS else None
    queue = [("pokegear", p) for p in ERRAND_PHASES] if err else []
    if pc:
        pc_phase = PC_TARGETS[target][2]
        # a save made at the PC (the boxed fixtures) is already inside: no door leg
        queue += ([] if start["map"] == pc.house_id else [("cherrygrove_pc", "enter")])
        queue += [("cherrygrove_pc", pc_phase)]
    if target == "hatch":
        queue += [("hatch", "hatch")]
    max_legs += len(queue) + (4 if pc else 0)  # a cutscene resync re-plans the same phase
    pc_extra = (
        {
            "run_from_wild": pack_legs(game, PC_LEGS)["run_from_wild"],
            "persistence": pack_legs(game, SAVE_LEGS),
            "ram": pack_ram(game),
            "synth": {
                "new_pid": synth["new_pid"],
                "otid": synth["otid"],
                "species": synth["species"],
                "kind": synth["kind"],
            },
            "profile": pack_profile_slice(game),
        }
        if kind
        else {}
    )
    final_ok = PC_TARGETS[target][1] if target in PC_TARGETS else "HATCH_OK"
    load_state = ""
    result: dict = {}
    history: list[dict] = []
    for leg in range(1, max_legs + 1):
        leg_start = start
        if queue:
            who, phase = queue[0]
            e = err if who == "pokegear" else pc
            if who == "hatch":
                route = plan_hatch(world, start, game)
            elif phase in ("deposit", "withdraw"):
                route = plan_pc(e, start, game, phase)
            else:
                route = plan_errand(world, e, phase, start, game)
            if who in ("cherrygrove_pc", "hatch"):
                route.update(pc_extra)
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
        if target == "grass":  # the wild-battle leg's own evidence: no SAVE, no reload
            result.update(
                staged_save=staged_save,
                plan={"path": str(rpath), "sha256": _sha256(rpath)},
                battle={
                    "witness": battle_witness(result),
                    "settled_state": settled_state(result["lines"]),
                },
            )
        history.append({**result, "kind": route.get("kind"), "phase": route.get("phase")})
        if kind and result["status"] == final_ok:
            # the lane's battery file, decoded by the independent PYDEC oracle, then a COLD RELOAD:
            # a fresh boot from that battery must still show the deposit (G2: boot -> SAVE -> reload)
            try:
                if target == "pc_withdraw":
                    result["saved"] = verify_saved_withdraw(
                        saved_path, game, synth, before_save, result["detail"]
                    )
                else:
                    result["saved"] = (verify_saved_hatch if target == "hatch" else verify_saved)(
                        saved_path, game, synth
                    )
                result["battery_sha1"] = sha1_of(saved_path)
                result["before_save"] = before_save
                result["save_witness"] = save_witness(saved_path, game)
                result["reload"] = _cold_reload(
                    rom_staged, ld, tag, leg, game, route, pc_extra, timeout, history
                )
                if result["reload"]["status"] != "RELOAD_OK":
                    result.update(status="RELOAD_FAIL", detail=result["reload"]["detail"])
                else:
                    # NOTE: the reload boot does not rewrite the battery, so this re-reads the SAME file: it
                    # is a consistency record, not independent evidence. The reload evidence is the Lua
                    # RELOAD_OK status (a fresh boot read back by RAM: party + box + dirty mask).
                    result["reload"]["witness"] = save_witness(saved_path, game)
                    assert_save_progress(before_save, result["save_witness"], result["reload"]["witness"])
            except RouteError as exc:
                result.update(status="SAVE_MISMATCH", detail=str(exc))
        if kind or target == "grass":
            gen4_evidence.bind({**binding, "rom_sha1": rom_sha1}, receipt_binding(title=GAMES[game][1]),
                               title=GAMES[game][1], rom_sha1=rom_sha1)
            result["receipt"] = build_receipt(game, save, synth, history, result, rom_sha1, binding=binding)
            (ld / f"{tag}_receipt.json").write_text(
                json.dumps(result["receipt"], indent=1), encoding="utf-8"
            )
        if result["status"] != "RESYNC":
            return result
        m = RESYNC_RE.search(result["detail"])
        if not m:
            return result
        start = {"map": int(m[1]), "x": int(m[2]), "y": int(m[3]), "dir": int(m[4])}
        done = m[5] != "0"  # logs without the field predate it: they only ever stopped a phase
        load_state = m[6].strip()
        if done and queue:
            queue.pop(0)
        elif not done and (start["map"], start["x"], start["y"]) == (
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
    rom, save, lane = {
        "hge": (HGE_ROM, HGE_SAVE, "route_hge"),
        "SS": (SS_ROM, SS_SAVE, "route_ss"),
    }.get(a.game, (DEFAULT_ROM, DEFAULT_SAVE, "route"))
    a.rom = a.rom or str(rom)
    a.save = a.save or str(save)
    a.pret = a.pret or str(DEFAULT_PRET)
    if hasattr(a, "lane"):
        a.lane = a.lane or lane
        a.tag = a.tag or a.lane


def _summary(route: dict) -> str:
    phase = next((p for p in ("deposit", "withdraw") if p in route), None)
    if phase:
        door = f"{route['enter']['tiles']} tiles to the door, " if "enter" in route else ""
        return f"PC {phase}: {door}{route[phase]['tiles']} inside"
    return f"{route['tiles']} tiles, {len(route['steps'])} segments, grass {route['grass']['tile']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    r = sub.add_parser("run", help="plan and drive the route live in lane <LANE_ROOT>/route[_hge]")
    for q in (p, r):
        q.add_argument("--game", choices=sorted(GAMES), default="HG")
        q.add_argument("--save")
        q.add_argument("--rom")
        q.add_argument("--pret")
    p.add_argument("--out")
    p.add_argument("--target", choices=["grass", "pc", "pc_withdraw", "hatch"], default="grass")
    r.add_argument("--lane")
    r.add_argument("--tag", help="state/log name prefix (default: the lane name)")
    r.add_argument("--errand", choices=["pokegear"], help="house visit before the route")
    r.add_argument(
        "--target",
        choices=["grass", "pc", "pc_withdraw", "hatch"],
        default="grass",
        help="grass: walk to a wild battle; pc: Cherrygrove PC deposit + native SAVE (needs a "
        "SYNTH party-2 --save); pc_withdraw: withdraw box 0 slot 0 + native SAVE + cold reload (needs "
        "a boxed SYNTH --save with party < 6); hatch: pace on plain floor until the SYNTH egg1 hatches, "
        "native SAVE + cold reload (see tools/gen4_synth_save.py)",
    )
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
                target=a.target,
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
        ok = PC_TARGETS[a.target][1] if a.target in PC_TARGETS else {"hatch": "HATCH_OK"}.get(a.target, "BATTLE")
        return 0 if res["status"] == ok else 1
    try:
        start = save_position(a.save, a.game)
        world = load_world(a.rom, a.pret)
        if a.target in PC_TARGETS:
            route = plan_pc_stop(a.rom, a.pret, world, start, a.game, PC_TARGETS[a.target][2])
        else:
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
        print(f"wrote {a.out}: {_summary(route)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
