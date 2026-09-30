"""Shared GBA map-geometry parser for every FireRed-based ROM (pret decomp structures).

Game geometry comes from the ROM/decomp, never from screenshots (owner rule). Radical Red
keeps the vanilla pret data structures (gMapGroups -> MapHeader -> MapLayout -> Tileset), so
this one reader works for vanilla FR/LG dumps, the RR base ROM, the RR companion build, and
any future hack built on the same engine -- only the gMapGroups address (or a .sym to resolve
it) changes per binary.

Struct references (pret/pokefirered, confirmed non-standard-safe since RR keeps them):
  include/global.fieldmap.h : struct MapHeader, struct MapLayout, struct MapEvents
  include/fieldmap.h:8       : NUM_METATILES_IN_PRIMARY 640
  include/constants/metatile_behaviors.h : MB_* behaviour byte constants (subset below)
  include/event_object_movement.h / include/global.fieldmap.h : ObjectEventTemplate/WarpEvent/
    CoordEvent/BgEvent field layouts (offsets as given by the card; verified against the
    FireRed cross-check test in tests/unit/test_gba_map.py)

GBA ROM addresses are 0x08000000 + file offset (ROM mirrors at 0x08000000-0x09FFFFFF).
"""
from __future__ import annotations

import argparse
import re
import struct
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ROM_BASE = 0x08000000
DEFAULT_GROUPS_ADDR = 0x083526A8  # FR US 1.0, gMapGroups (data/gen3/pret/pokefirered.sym)
NUM_METATILES_IN_PRIMARY = 640  # include/fieldmap.h:8

# A small, cited subset of include/constants/metatile_behaviors.h -- add more as callers need.
MB_TALL_GRASS = 0x02
MB_JUMP_EAST = 0x38
MB_JUMP_WEST = 0x39
MB_JUMP_NORTH = 0x3A
MB_JUMP_SOUTH = 0x3B
MB_PC = 0x83

# Ledge behaviours block entry by default in Map.bfs (a ledge can only be jumped DOWN off of,
# never walked into from the low side) -- ponytail: directional ledge legality isn't modeled,
# they're simply avoided; add per-direction rules if a route needs to jump one.
DEFAULT_AVOID_BEHAVIOURS = (MB_JUMP_EAST, MB_JUMP_WEST, MB_JUMP_NORTH, MB_JUMP_SOUTH)

_DIR_DELTAS = {
    "Up": (0, -1),
    "Down": (0, 1),
    "Left": (-1, 0),
    "Right": (1, 0),
}


def _addr_to_offset(addr: int) -> int:
    return addr - ROM_BASE if addr >= ROM_BASE else addr


@dataclass
class WarpEvent:
    x: int
    y: int
    elevation: int
    warp_id: int
    map_num: int
    map_group: int


@dataclass
class ObjectEvent:
    local_id: int
    graphics_id: int
    kind: int
    x: int
    y: int
    elevation: int
    movement_type: int


@dataclass
class CoordEvent:
    x: int
    y: int
    elevation: int
    trigger: int
    index: int
    script: int


@dataclass
class BgEvent:
    x: int
    y: int
    elevation: int
    kind: int
    script_or_item: int


# struct MapConnection direction byte (pret include/global.fieldmap.h) -> our string name.
CONNECTION_DIRECTIONS = {1: "down", 2: "up", 3: "left", 4: "right"}


@dataclass
class Connection:
    """One MapHeader.connections entry (pret include/global.fieldmap.h struct MapConnection),
    plus the destination map's own width/height (a cheap extra header read at parse time) so
    `arrival()` can place the player on the destination's edge row/column without a second
    Rom lookup.

    direction is named from THIS map's edge the connection sits on -- "up" means this map's
    TOP edge leads to `map_group`.`map_num` (verified against the real FR US 1.0 ROM,
    tools/gba_map.py --connections: PalletTown(3.0) has (direction=up, offset=0) -> Route1
    (3.19), Route1 has (direction=up, offset=-12) -> ViridianCity(3.1) and
    (direction=down, offset=0) -> PalletTown(3.0), ViridianCity has (direction=down,
    offset=12) -> Route1(3.19) -- exactly the offsets already cited in
    lua/tests/gen3_scripted_play.lua's PATHS comments).
    """
    direction: str
    offset: int
    map_group: int
    map_num: int
    dest_width: int
    dest_height: int


def arrival(direction: str, from_map: Map, x: int):
    """Where crossing `from_map`'s `direction` edge at coordinate `x` lands.

    Returns (dest_group, dest_num, x_dest, y_dest), or None if `from_map` has no connection in
    that direction.

    THE RULE (re-derived from the real ROM's own connection offsets, since no pret decomp
    checkout is present in this worktree to cite a source line -- physically verified above,
    and it reproduces every offset the driver's PATHS comments already had independently):
    crossing a map connection does NOT land one tile inside the destination -- it lands ON
    the destination's edge row/column. Leaving through this map's "up"/"down" edge lands on
    the destination's opposite row (its bottom row y=height-1 for "up", its top row y=0 for
    "down"); "left"/"right" is the same rule on columns. The coordinate along the shared edge
    translates via `other = this - offset` (matches the "this_x = other_x + offset" convention
    lua/tests/gen3_scripted_play.lua already cited, verified both ways: PalletTown(12,1) up
    offset=0 -> Route1 x=12,y=39 [height-1]; Route1(12,39) down offset=0 -> PalletTown x=12,
    y=0; Route1 up offset=-12 -> ViridianCity x=Route1_x+12; ViridianCity down offset=12 ->
    Route1 x=ViridianCity_x-12).
    """
    conn = next((c for c in from_map.connections if c.direction == direction), None)
    if conn is None:
        return None
    other = x - conn.offset
    if direction == "up":
        return conn.map_group, conn.map_num, other, conn.dest_height - 1
    if direction == "down":
        return conn.map_group, conn.map_num, other, 0
    if direction == "left":
        return conn.map_group, conn.map_num, conn.dest_width - 1, other
    if direction == "right":
        return conn.map_group, conn.map_num, 0, other
    raise ValueError(f"unknown connection direction {direction!r}")


@dataclass
class Map:
    width: int
    height: int
    collision: list  # [y][x] -> int 0-3
    behaviour: list  # [y][x] -> int 0-255
    warps: list = field(default_factory=list)
    objects: list = field(default_factory=list)
    coords: list = field(default_factory=list)
    bg: list = field(default_factory=list)
    connections: list = field(default_factory=list)

    def find_behaviour(self, behaviour: int) -> list:
        return [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if self.behaviour[y][x] == behaviour
        ]

    def bfs(
        self,
        src: tuple,
        dst: tuple,
        avoid_behaviours: tuple = DEFAULT_AVOID_BEHAVIOURS,
        block_npcs: bool = True,
    ):
        """4-directional shortest path avoiding collision, blocked NPC spawn tiles, and the
        given ledge/avoid behaviours. Returns a list of "Up"/"Down"/"Left"/"Right" or None."""
        blocked_npc = {(o.x, o.y) for o in self.objects} if block_npcs else set()

        def walkable(x: int, y: int) -> bool:
            if not (0 <= x < self.width and 0 <= y < self.height):
                return False
            if self.collision[y][x] != 0:
                return False
            if (x, y) in blocked_npc:
                return False
            return self.behaviour[y][x] not in avoid_behaviours

        if not walkable(*dst) and dst != src:
            return None

        queue = deque([src])
        came_from = {src: None}
        while queue:
            cur = queue.popleft()
            if cur == dst:
                path = []
                node = cur
                while came_from[node] is not None:
                    prev, direction = came_from[node]
                    path.append(direction)
                    node = prev
                path.reverse()
                return path
            for direction, (dx, dy) in _DIR_DELTAS.items():
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in came_from:
                    continue
                if not walkable(*nxt):
                    continue
                came_from[nxt] = (cur, direction)
                queue.append(nxt)
        return None

    @staticmethod
    def lua_paths_entry(name: str, map_name: str, src: tuple, dst: tuple, dirs: list) -> str:
        dirs_str = ", ".join(f'"{d}"' for d in dirs)
        return (
            f"{name} = {{\n"
            f'    map = "{map_name}", from = {{ {src[0]}, {src[1]} }}, '
            f"to = {{ {dst[0]}, {dst[1]} }},\n"
            f"    dirs = {{ {dirs_str} }},\n"
            f"}},"
        )


class Rom:
    # struct Tileset.metatileAttributes: FR/LG/RR (pret pokefirered include/global.fieldmap.h)
    # declare it `const u32 *` at offset 0x14; Emerald (pret pokeemerald include/global.fieldmap.h)
    # declares it `const u16 *` at offset 0x10 -- a real format difference, not a renumbering
    # (verified: reading Route102's known tall-grass patch as u32@0x14 returns behaviour bytes
    # that are never MB_TALL_GRASS(0x02) anywhere on the map; as u16@0x10 the same patch reads
    # 0x02 exactly where the wild-encounter grass sits). `game="fr"` (default) preserves this
    # tool's original FR/LG/RR-only behaviour byte for byte.
    _ATTR_LAYOUT = {"fr": (0x14, 4), "emerald": (0x10, 2)}

    def __init__(self, data: bytes, groups_addr: int, game: str = "fr"):
        self.data = data
        self.groups_addr = groups_addr
        if game not in self._ATTR_LAYOUT:
            raise ValueError(f"unknown game {game!r} (want {sorted(self._ATTR_LAYOUT)})")
        self.game = game

    def _u8(self, addr: int) -> int:
        off = _addr_to_offset(addr)
        return self.data[off]

    def _u16(self, addr: int) -> int:
        off = _addr_to_offset(addr)
        return struct.unpack_from("<H", self.data, off)[0]

    def _s32(self, addr: int) -> int:
        off = _addr_to_offset(addr)
        return struct.unpack_from("<i", self.data, off)[0]

    def _u32(self, addr: int) -> int:
        off = _addr_to_offset(addr)
        return struct.unpack_from("<I", self.data, off)[0]

    def _ptr(self, addr: int) -> int:
        return self._u32(addr)

    def _header_ptr(self, group: int, num: int) -> int:
        group_ptr = self._ptr(self.groups_addr + group * 4)
        return self._ptr(group_ptr + num * 4)

    def _map_dims(self, group: int, num: int) -> tuple:
        """Just width/height, for Connection.dest_* -- far cheaper than a full Map() (no
        block/attribute walk)."""
        layout_ptr = self._ptr(self._header_ptr(group, num) + 0x00)
        return self._s32(layout_ptr + 0x00), self._s32(layout_ptr + 0x04)

    def map(self, group: int, num: int) -> Map:
        header_ptr = self._header_ptr(group, num)

        layout_ptr = self._ptr(header_ptr + 0x00)
        events_ptr = self._ptr(header_ptr + 0x04)
        # MapHeader.connections* -- offset 0x0C, PHYSICALLY VERIFIED against the FR US 1.0
        # ROM here (no pret decomp checkout present in this worktree to cite a source line):
        # header_ptr+0x0C for PalletTown(3.0) decodes to {count=2, [(dir=up,off=0)->3.19,
        # (dir=down,off=0)->3.39]}, and Route1(3.19)/ViridianCity(3.1) decode to exactly the
        # offsets lua/tests/gen3_scripted_play.lua's PATHS comments already cited independently
        # (up=-12/down=0 and down=12) -- +0x08 there decodes to garbage (a non-ROM pointer).
        connections_ptr = self._ptr(header_ptr + 0x0C)

        width = self._s32(layout_ptr + 0x00)
        height = self._s32(layout_ptr + 0x04)
        blocks_ptr = self._ptr(layout_ptr + 0x0C)
        primary_tileset_ptr = self._ptr(layout_ptr + 0x10)
        secondary_tileset_ptr = self._ptr(layout_ptr + 0x14)

        attrs_off, attrs_width = self._ATTR_LAYOUT[self.game]
        attrs_read = self._u16 if attrs_width == 2 else self._u32
        primary_attrs_ptr = self._ptr(primary_tileset_ptr + attrs_off)
        secondary_attrs_ptr = self._ptr(secondary_tileset_ptr + attrs_off)

        collision = [[0] * width for _ in range(height)]
        behaviour = [[0] * width for _ in range(height)]
        for y in range(height):
            for x in range(width):
                word = self._u16(blocks_ptr + (y * width + x) * 2)
                metatile_id = word & 0x3FF
                coll = (word >> 10) & 0x3
                collision[y][x] = coll
                if metatile_id < NUM_METATILES_IN_PRIMARY:
                    attrs_ptr = primary_attrs_ptr
                    local_id = metatile_id
                else:
                    attrs_ptr = secondary_attrs_ptr
                    local_id = metatile_id - NUM_METATILES_IN_PRIMARY
                attr = attrs_read(attrs_ptr + local_id * attrs_width)
                behaviour[y][x] = attr & 0xFF

        result = Map(width=width, height=height, collision=collision, behaviour=behaviour)

        if events_ptr:
            object_count = self._u8(events_ptr + 0)
            warp_count = self._u8(events_ptr + 1)
            coord_count = self._u8(events_ptr + 2)
            bg_count = self._u8(events_ptr + 3)
            objects_ptr = self._ptr(events_ptr + 4)
            warps_ptr = self._ptr(events_ptr + 8)
            coords_ptr = self._ptr(events_ptr + 12)
            bg_ptr = self._ptr(events_ptr + 16)

            for i in range(object_count):
                base = objects_ptr + i * 24
                result.objects.append(
                    ObjectEvent(
                        local_id=self._u8(base + 0),
                        graphics_id=self._u8(base + 1),
                        kind=self._u8(base + 2),
                        x=self._u16(base + 4),
                        y=self._u16(base + 6),
                        elevation=self._u8(base + 8),
                        movement_type=self._u8(base + 9),
                    )
                )

            for i in range(warp_count):
                base = warps_ptr + i * 8
                result.warps.append(
                    WarpEvent(
                        x=self._u16(base + 0),
                        y=self._u16(base + 2),
                        elevation=self._u8(base + 4),
                        warp_id=self._u8(base + 5),
                        map_num=self._u8(base + 6),
                        map_group=self._u8(base + 7),
                    )
                )

            for i in range(coord_count):
                base = coords_ptr + i * 16
                result.coords.append(
                    CoordEvent(
                        x=self._u16(base + 0),
                        y=self._u16(base + 2),
                        elevation=self._u8(base + 4),
                        trigger=self._u16(base + 6),
                        index=self._u16(base + 8),
                        script=self._u32(base + 12),
                    )
                )

            for i in range(bg_count):
                base = bg_ptr + i * 12
                result.bg.append(
                    BgEvent(
                        x=self._u16(base + 0),
                        y=self._u16(base + 2),
                        elevation=self._u8(base + 4),
                        kind=self._u8(base + 5),
                        script_or_item=self._u32(base + 8),
                    )
                )

        if connections_ptr:
            count = self._s32(connections_ptr + 0x00)
            arr_ptr = self._ptr(connections_ptr + 0x04)
            if count > 0 and arr_ptr:
                for i in range(count):
                    base = arr_ptr + i * 12  # struct MapConnection, 12 bytes
                    direction = CONNECTION_DIRECTIONS.get(self._u8(base + 0x00))
                    offset = self._s32(base + 0x04)
                    dest_group = self._u8(base + 0x08)
                    dest_num = self._u8(base + 0x09)
                    if direction is None:
                        continue  # an unknown direction byte is not a connection worth trusting
                    dest_width, dest_height = self._map_dims(dest_group, dest_num)
                    result.connections.append(Connection(
                        direction=direction, offset=offset,
                        map_group=dest_group, map_num=dest_num,
                        dest_width=dest_width, dest_height=dest_height,
                    ))

        return result


def resolve_groups_addr(sym_path) -> int:
    text = Path(sym_path).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^([0-9a-fA-F]{8})\s+\S+\s+\S+\s+gMapGroups\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"gMapGroups symbol not found in {sym_path}")
    return int(match.group(1), 16)


def load(rom_path, groups_addr: int = None, sym_path=None, game: str = "fr") -> Rom:
    data = Path(rom_path).read_bytes()
    if sym_path is not None:
        groups_addr = resolve_groups_addr(sym_path)
    elif groups_addr is None:
        groups_addr = DEFAULT_GROUPS_ADDR
    return Rom(data, groups_addr, game=game)


def _parse_group_num(text: str):
    group_s, num_s = text.split(".")
    return int(group_s), int(num_s)


def _parse_xy(text: str):
    x_s, y_s = text.split(",")
    return int(x_s), int(y_s)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom")
    parser.add_argument("--groups-addr", type=lambda s: int(s, 0), default=None)
    parser.add_argument("--sym")
    parser.add_argument("--game", choices=sorted(Rom._ATTR_LAYOUT), default="fr",
                         help="metatile-attribute format: fr (u32@0x14, default) or emerald (u16@0x10)")
    parser.add_argument("--map", required=True, help="group.num, e.g. 5.4")
    parser.add_argument("--find-behaviour", type=lambda s: int(s, 0))
    parser.add_argument("--bfs", nargs=2, metavar=("SRC", "DST"))
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--connections", action="store_true")
    args = parser.parse_args(argv)

    rom = load(args.rom, groups_addr=args.groups_addr, sym_path=args.sym, game=args.game)
    group, num = _parse_group_num(args.map)
    m = rom.map(group, num)

    print(
        f"map {group}.{num}: {m.width}x{m.height}, {len(m.warps)} warps, "
        f"{len(m.objects)} objects, {len(m.coords)} coords, {len(m.bg)} bg, "
        f"{len(m.connections)} connections"
    )

    if args.connections:
        for c in m.connections:
            print(
                f"connection {c.direction}: offset={c.offset} -> {c.map_group}.{c.map_num} "
                f"({c.dest_width}x{c.dest_height})"
            )

    if args.find_behaviour is not None:
        tiles = m.find_behaviour(args.find_behaviour)
        print(f"behaviour 0x{args.find_behaviour:02x} tiles: {tiles}")

    if args.bfs:
        src = _parse_xy(args.bfs[0])
        dst = _parse_xy(args.bfs[1])
        path = m.bfs(src, dst)
        print(f"bfs {src} -> {dst}: {path}")

    if args.dump:
        for y in range(m.height):
            print("".join("#" if m.collision[y][x] else "." for x in range(m.width)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
