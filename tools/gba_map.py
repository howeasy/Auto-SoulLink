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
    def __init__(self, data: bytes, groups_addr: int):
        self.data = data
        self.groups_addr = groups_addr

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

    def map(self, group: int, num: int) -> Map:
        group_ptr = self._ptr(self.groups_addr + group * 4)
        header_ptr = self._ptr(group_ptr + num * 4)

        layout_ptr = self._ptr(header_ptr + 0x00)
        events_ptr = self._ptr(header_ptr + 0x04)

        width = self._s32(layout_ptr + 0x00)
        height = self._s32(layout_ptr + 0x04)
        blocks_ptr = self._ptr(layout_ptr + 0x0C)
        primary_tileset_ptr = self._ptr(layout_ptr + 0x10)
        secondary_tileset_ptr = self._ptr(layout_ptr + 0x14)

        primary_attrs_ptr = self._ptr(primary_tileset_ptr + 0x14)
        secondary_attrs_ptr = self._ptr(secondary_tileset_ptr + 0x14)

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
                attr = self._u32(attrs_ptr + local_id * 4)
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

        return result


def resolve_groups_addr(sym_path) -> int:
    text = Path(sym_path).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^([0-9a-fA-F]{8})\s+\S+\s+\S+\s+gMapGroups\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"gMapGroups symbol not found in {sym_path}")
    return int(match.group(1), 16)


def load(rom_path, groups_addr: int = None, sym_path=None) -> Rom:
    data = Path(rom_path).read_bytes()
    if sym_path is not None:
        groups_addr = resolve_groups_addr(sym_path)
    elif groups_addr is None:
        groups_addr = DEFAULT_GROUPS_ADDR
    return Rom(data, groups_addr)


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
    parser.add_argument("--map", required=True, help="group.num, e.g. 5.4")
    parser.add_argument("--find-behaviour", type=lambda s: int(s, 0))
    parser.add_argument("--bfs", nargs=2, metavar=("SRC", "DST"))
    parser.add_argument("--dump", action="store_true")
    args = parser.parse_args(argv)

    rom = load(args.rom, groups_addr=args.groups_addr, sym_path=args.sym)
    group, num = _parse_group_num(args.map)
    m = rom.map(group, num)

    print(
        f"map {group}.{num}: {m.width}x{m.height}, {len(m.warps)} warps, "
        f"{len(m.objects)} objects, {len(m.coords)} coords, {len(m.bg)} bg"
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
