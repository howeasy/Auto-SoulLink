#!/usr/bin/env python3
"""Generate Gen 1 wild encounter tables from pret/pokered raw asm.

Reads:
    .cache/pret/pokered/data/wild/grass_water.asm          (map_id → label)
    .cache/pret/pokered/data/wild/maps/*.asm               (per-map encounter slots)
    .cache/pret/pokered/constants/pokemon_constants.asm    (species name → internal idx)
    data/games/gen1_rby/area_map.json                      (map_id → area_id)
    data/games/gen1_rby/species_index.json                 (internal idx → NatDex)

Writes:
    data/games/gen1_rby/encounter_tables.json

Slot percentages per pret/data/wild/probabilities.asm:
    slot 0,1: 20%   slot 2: 15%   slots 3-5: 10%   slots 6-7: 5%   slot 8: 4%   slot 9: 1%

Per-species rates are summed across all slots the species occupies.
Min/max levels are min/max across those slots.

``--foundation purergb`` switches to a second, independent pipeline (docs/purergb/PLAN.md M1):
species are stored as INTERNAL indices (not NatDex -- pureRGB's internal/dex mapping is
many-to-one, see A13), MISSINGNO rows are kept (dex 0 is a real catchable species there), and
the grass/water tables are read from the BUILT ROM's ``WildDataPointers`` (bank $2C) and
cross-checked against the source parse -- 0 mismatches is the exit gate (W1). Fishing (old/good/
super rod) is generated only for purergb; vanilla's file has never carried fishing rows. The
``--foundation pret`` (default) path is untouched byte-for-byte by this addition.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools.gen1_foundation as gf  # noqa: E402

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, ".."))
def _find_pret(name: str) -> str:
    """Locate a decomp checkout, searching upward from the repo.

    A git WORKTREE has no .cache of its own — it lives under the main repo's
    .claude/worktrees/, so the decomps are several directories up. Without this the
    generator cannot run in a worktree at all.
    """
    env = os.environ.get("SLINK_PRET_DIR" if name == "pokered" else "SLINK_PRET_YELLOW_DIR")
    if env:
        return env
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(_REPO, ".cache", "pret", name)


_PRET = _find_pret("pokered")
_PRET_YELLOW = _find_pret("pokeyellow")
_OUT = os.path.join(_REPO, "data", "games", "gen1_rby", "encounter_tables.json")
_FLOORS_OUT = os.path.join(_REPO, "data", "games", "gen1_rby", "floor_labels.json")
_AREA_MAP = os.path.join(_REPO, "data", "games", "gen1_rby", "area_map.json")
_SPECIES_INDEX = os.path.join(_REPO, "data", "games", "gen1_rby", "species_index.json")

SLOT_RATES = [20, 20, 15, 10, 10, 10, 5, 5, 4, 1]  # must sum to 100

# Species constants with non-trivial display names (special characters etc.)
SPECIES_DISPLAY_OVERRIDES = {
    "NIDORAN_F": "Nidoran♀",
    "NIDORAN_M": "Nidoran♂",
    "FARFETCH_D": "Farfetch'd",
    "MR_MIME": "Mr. Mime",
    "MRMIME": "Mr. Mime",
}


def parse_pokemon_constants(path: str) -> dict[str, int]:
    """SPECIES_NAME → internal index (0..190).

    pret pokemon_constants.asm uses `const_def` (starts at $00 with NO_MON)
    followed by `const NAME` declarations that increment by 1. `const_skip`
    is a MissingNo placeholder that also increments the index without
    registering a name.
    """
    out: dict[str, int] = {}
    idx = -1
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if line == "const_def":
                idx = 0
                continue
            if line == "const_skip":
                if idx >= 0:
                    idx += 1
                continue
            m = re.match(r"^const\s+([A-Z_0-9]+)\s*$", line)
            if m and idx >= 0:
                out[m.group(1)] = idx
                idx += 1
    return out


def parse_wild_pointers(path: str) -> list[tuple[int, str]]:
    """Return list of (map_id, label_symbol) for each `dw Foo` in WildDataPointers.

    Stops at the `assert_table_length NUM_MAPS` line.
    """
    out: list[tuple[int, str]] = []
    in_table = False
    idx = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if line.startswith("WildDataPointers"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("assert_table_length"):
                break
            m = re.match(r"^dw\s+([A-Za-z_0-9]+)\s*$", line)
            if m:
                out.append((idx, m.group(1)))
                idx += 1
    return out


def floor_label(label: str, area_id: str, map_id_to_area=None, map_id=None) -> str:
    """A short floor name for a multi-map area, from the wild-data label.

    The labels carry it already -- `MtMoonB1FWildMons`, `SeafoamIslandsB4FWildMons`,
    `VictoryRoad2FWildMons` -- so this strips the `WildMons` suffix and the area's own
    CamelCase prefix and keeps what is left. Falls back to the bare label when nothing
    recognisable remains, which is still more informative than silently dropping the floor.
    """
    name = label[:-len("WildMons")] if label.endswith("WildMons") else label
    # The area prefix is the label with the floor removed; comparing CamelCase to
    # snake_case directly is fragile, so compare on letters only.
    flat_area = area_id.replace("_", "").lower()
    i = 0
    while i < len(name) and name[:i + 1].lower() == flat_area[:i + 1]:
        i += 1
    rest = name[i:]
    return rest or name


def find_map_asm(label: str, repo: str = _PRET) -> str | None:
    """Resolve a wild label (e.g. Route1WildMons) to its .asm path."""
    name = label[: -len("WildMons")] if label.endswith("WildMons") else label
    candidate = os.path.join(repo, "data", "wild", "maps", f"{name}.asm")
    if os.path.exists(candidate):
        return candidate
    return None


_IF_DEF_RE = re.compile(r"^IF\s+DEF\(\s*([A-Za-z_0-9]+)\s*\)\s*$")


def parse_map_asm(path: str, defines: frozenset[str] = frozenset()
                  ) -> tuple[int, list[tuple[int, str]], int, list[tuple[int, str]]]:
    """Parse one wild map .asm. Returns (grass_rate, grass_entries, water_rate, water_entries).

    Each entry is (level, species_const). A slot table is exactly 10 entries when present.

    34 of pokered's 59 wild maps split their table with `IF DEF(_RED)` / `IF DEF(_BLUE)`,
    so `defines` selects the branch to keep. Ignoring the directives concatenated BOTH
    branches — Route 2 yielded 15 slots instead of 10, and since aggregate() maps slot
    index to a fixed rate, every species past the split got the wrong rate (or none) and
    Red's table was contaminated with Blue's exclusives. pokeyellow has no conditionals.
    """
    grass_rate = 0
    water_rate = 0
    grass: list[tuple[int, str]] = []
    water: list[tuple[int, str]] = []
    section = None  # 'grass' | 'water' | None
    cond_stack: list[bool] = []   # one entry per open IF; False = branch not taken
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            m = _IF_DEF_RE.match(line)
            if m:
                cond_stack.append(m.group(1) in defines)
                continue
            if line == "ENDC":
                if cond_stack:
                    cond_stack.pop()
                continue
            if line == "ELSE":
                if cond_stack:
                    cond_stack[-1] = not cond_stack[-1]
                continue
            if not all(cond_stack):
                continue
            m = re.match(r"^def_grass_wildmons\s+(\d+)\s*$", line)
            if m:
                grass_rate = int(m.group(1))
                section = "grass"
                continue
            m = re.match(r"^def_water_wildmons\s+(\d+)\s*$", line)
            if m:
                water_rate = int(m.group(1))
                section = "water"
                continue
            if line == "end_grass_wildmons" or line == "end_water_wildmons":
                section = None
                continue
            m = re.match(r"^db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", line)
            if m and section is not None:
                level = int(m.group(1))
                species = m.group(2)
                (grass if section == "grass" else water).append((level, species))
    return grass_rate, grass, water_rate, water


def species_display_name(species_const: str) -> str:
    if species_const in SPECIES_DISPLAY_OVERRIDES:
        return SPECIES_DISPLAY_OVERRIDES[species_const]
    return species_const.title().replace("_", " ")


def aggregate(entries: list[tuple[int, str]], drop: tuple[str, ...] = ("NO_MON", "MISSINGNO")
             ) -> list[dict]:
    """Collapse 10-slot list to per-species rate + min/max levels.

    Drops any species const named in ``drop`` -- vanilla drops MISSINGNO and NO_MON (a species
    that can't be identified isn't a species a client can classify); purergb keeps MISSINGNO
    (a real catchable species there, task spec "dex 0 kept") and passes ``drop=("NO_MON",)``.
    """
    by_species: dict[str, dict] = {}
    for slot, (level, sp) in enumerate(entries):
        if sp in drop:
            continue
        rate = SLOT_RATES[slot] if slot < len(SLOT_RATES) else 0
        if sp not in by_species:
            by_species[sp] = {"_const": sp, "rate": 0, "min_level": level, "max_level": level}
        cur = by_species[sp]
        cur["rate"] += rate
        cur["min_level"] = min(cur["min_level"], level)
        cur["max_level"] = max(cur["max_level"], level)
    return list(by_species.values())


def build_variant(repo: str, defines: frozenset[str], index_to_natdex: dict[int, int],
                  map_id_to_area: dict[int, str]) -> tuple[dict, list, set]:
    """Encounter tables for ONE game version. Returns (areas, skipped_areas, skipped_species)."""
    species_consts = parse_pokemon_constants(
        os.path.join(repo, "constants", "pokemon_constants.asm")
    )
    pointers = parse_wild_pointers(os.path.join(repo, "data", "wild", "grass_water.asm"))

    # ONE RULE AREA PER DUNGEON, BUT EVERY FLOOR'S TABLE.
    # This used to be first-wins: a dungeon spans several maps, they all resolve to one
    # area_id, and only the first map's table survived. Twenty of the fifty-nine tables in
    # the ROM were therefore unreachable -- Mt. Moon's B1F and B2F, all four Seafoam
    # basements, Victory Road 2F and 3F, both Rock Tunnel floors, and so on. A player
    # standing on B2F was shown 1F's encounters, which is worse than showing none.
    #
    # The area_id is NOT split, deliberately: it is the unit the Soul Link rules lock and
    # dead-zone, and splitting it would silently change what a run means. Instead the floor
    # goes on the METHOD axis, which is already a display grouping -- "Grass" becomes
    # "Grass B1F" for a multi-floor area and stays plain "Grass" for the 26 areas that are
    # a single map. Nothing that looks a table up by area_id sees any change.
    areas: dict[str, dict] = {}
    # map_id -> " B1F", published so the ROM SCANNER can label a randomized cartridge's
    # floors the same way. Both paths have to agree exactly: a clean ROM scanned at runtime
    # must reproduce this file byte for byte, which is the known-positive control that
    # proves the scanner reads real structure rather than something plausible.
    floor_suffix_by_map: dict[int, str] = {}
    # area_id -> how many maps carry wild data, so single-map areas keep unsuffixed labels.
    floors_per_area: dict[str, int] = {}
    for _mid, _label in pointers:
        if _label == "NothingWildMons":
            continue
        _aid = map_id_to_area.get(_mid)
        if _aid:
            floors_per_area[_aid] = floors_per_area.get(_aid, 0) + 1
    skipped_unknown_area: list[tuple[int, str]] = []
    skipped_unknown_species: set[str] = set()

    for map_id, label in pointers:
        if label == "NothingWildMons":
            continue
        area_id = map_id_to_area.get(map_id)
        if not area_id:
            skipped_unknown_area.append((map_id, label))
            continue
        asm_path = find_map_asm(label, repo)
        if not asm_path:
            sys.stderr.write(f"WARN: no asm for label {label} (map_id {map_id})\n")
            continue
        grass_rate, grass, water_rate, water = parse_map_asm(asm_path, defines)

        # The floor suffix comes from the wild-data label, which carries it already
        # (MtMoonB1FWildMons, SeafoamIslandsB4FWildMons). Only used when the area has more
        # than one map, so the common case reads exactly as it always did.
        suffix = ""
        if floors_per_area.get(area_id, 0) > 1:
            suffix = " " + floor_label(label, area_id, map_id_to_area, map_id)
            floor_suffix_by_map[map_id] = suffix

        block: dict[str, list[dict]] = areas.setdefault(area_id, {})
        for method, rate, entries in (("Grass" + suffix, grass_rate, grass),
                                       ("Water" + suffix, water_rate, water)):
            if rate == 0 or not entries:
                continue
            agg = aggregate(entries)
            method_entries = []
            for e in agg:
                idx = species_consts.get(e["_const"])
                if idx is None:
                    skipped_unknown_species.add(e["_const"])
                    continue
                natdex = index_to_natdex.get(idx)
                if not natdex:
                    skipped_unknown_species.add(e["_const"])
                    continue
                method_entries.append({
                    "species_id": natdex,
                    "name": species_display_name(e["_const"]),
                    "rate": e["rate"],
                    "min_level": e["min_level"],
                    "max_level": e["max_level"],
                })
            if method_entries:
                method_entries.sort(key=lambda x: (-x["rate"], x["species_id"]))
                block[method] = method_entries
        if not block:
            areas.pop(area_id, None)

    return areas, skipped_unknown_area, skipped_unknown_species, floor_suffix_by_map


# variant -> (repo path, rgbasm defines). Yellow is its own decomp and has no conditionals.
VARIANTS = {
    "red":    (_PRET, frozenset({"_RED"})),
    "blue":   (_PRET, frozenset({"_BLUE"})),
    "yellow": (_PRET_YELLOW, frozenset()),
}

# ---------------------------------------------------------------------------------------------
# pureRGB pipeline (docs/purergb/PLAN.md M1). Species are INTERNAL indices; MISSINGNO is kept;
# grass/water come off the BUILT ROM's WildDataPointers (bank $2C) and are cross-checked against
# the source parse; fishing (old/good/super rod) is generated only here.
# ---------------------------------------------------------------------------------------------

_PURERGB_TITLES = ["purered", "pureblue", "puregreen"]
_PURERGB_SLOT_CHANCES_256 = [51, 51, 39, 25, 25, 25, 13, 13, 11, 3]  # WildMonEncounterSlotChances


def _purergb_out_paths():
    d = gf.data_dir("purergb")
    return d / "encounter_tables.json", d / "area_map.json", d / "floor_labels.json"


def parse_name_array(text: str, header: str) -> list[str]:
    """``header::`` followed by ``dname "..."`` rows, in order -- pureRGB's names.asm shape."""
    out: list[str] = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(header + ":"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("assert_table_length"):
            break
        m = re.match(r'^dname\s+"(.*)"\s*$', line)
        if m:
            out.append(m.group(1))
    return out


def parse_map_id_list(text: str, header: str) -> list[str]:
    """``header:`` followed by ``db CONST`` rows terminated by ``db -1``."""
    out: list[str] = []
    in_table = False
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith(header + ":"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("db -1"):
            break
        m = re.match(r"^db\s+([A-Za-z_0-9]+)\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def parse_super_rod_rows(text: str) -> list[tuple[str, str]]:
    """SuperRodData: ``dbw MAP, GroupN`` rows, terminated by ``db -1``."""
    out: list[tuple[str, str]] = []
    in_table = False
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("SuperRodData:"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("db -1"):
            break
        m = re.match(r"^dbw\s+([A-Za-z_0-9]+)\s*,\s*(\S+)\s*$", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def parse_super_rod_groups(text: str) -> dict[str, list[tuple[int, str]]]:
    groups: dict[str, list[tuple[int, str]]] = {}
    cur = None
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^(Group\d+):\s*$", line)
        if m:
            cur = m.group(1)
            groups[cur] = []
            continue
        if cur is None:
            continue
        if re.match(r"^db\s+\d+\s*$", line):  # the leading "how many mons" count line
            continue
        m = re.match(r"^db\s+(\d+)\s*,\s*(\S+)\s*$", line)
        if m:
            groups[cur].append((int(m.group(1)), m.group(2)))
    return groups


def parse_good_rod_pools(text: str) -> dict[str, list[tuple[int, str]]]:
    pools: dict[str, list[tuple[int, str]]] = {}
    cur = None
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^(GoodRodMons|GoodRodMonsOcean):\s*$", line)
        if m:
            cur = m.group(1)
            pools[cur] = []
            continue
        if cur is None:
            continue
        m = re.match(r"^db\s+(-?\d+)\s*,\s*(\S+)\s*$", line)
        if m:
            lvl = int(m.group(1))
            if lvl == -1:
                cur = None
                continue
            pools[cur].append((lvl, m.group(2)))
    return pools


def _even_rates(n: int) -> list[int]:
    """n rates in [0, 100] summing to exactly 100, as equal as the rejection-sampled RNG."""
    base, rem = divmod(100, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _rom_wild_block(rom: bytes, flat_off: int) -> tuple[int, list[tuple[int, int]], int]:
    """(rate, [(level, species_byte)]*10 or [], next_flat_offset)."""
    rate = rom[flat_off]
    if rate == 0:
        return rate, [], flat_off + 1
    slots = []
    p = flat_off + 1
    for _ in range(10):
        slots.append((rom[p], rom[p + 1]))
        p += 2
    return rate, slots, p


def build_purergb_title(title: str, root, species_to_id: dict[str, int], id_to_name: dict[int, str],
                        map_id_to_area: dict[int, str], floor_labels: dict[str, str],
                        ocean_ids: set[int], good_rod_pools: dict[str, list[tuple[int, str]]],
                        super_rod_group_by_map: dict[int, str],
                        super_rod_groups: dict[str, list[tuple[int, str]]]) -> dict[str, dict]:
    """Build one title's {area_id: {method: [entries]}}, ROM-verified against ``title``."""
    pointers = parse_wild_pointers(str(root / "data" / "wild" / "grass_water.asm"))
    maps_dir = root / "data" / "wild" / "maps"
    label_to_path = {p.stem + "WildMons": p for p in maps_dir.glob("*.asm")}
    label_to_path["NothingWildMons"] = maps_dir / "nothing.asm"

    syms = gf.parse_sym(gf.sym_path("purergb", title))
    bank, addr = syms["WildDataPointers"]
    if (bank, addr) != (0x2C, 0x484A):
        raise SystemExit(f"{title}: WildDataPointers moved to {bank:02x}:{addr:04x}, expected 2c:484a")
    rom = gf.rom_path("purergb", title).read_bytes()
    ptr_flat = gf.flat(bank, addr)
    rom_ptrs = []
    off = ptr_flat
    while True:
        ptr = rom[off] | (rom[off + 1] << 8)
        off += 2
        if ptr == 0xFFFF:
            break
        rom_ptrs.append(ptr)
    if len(rom_ptrs) != len(pointers):
        raise SystemExit(f"{title}: ROM has {len(rom_ptrs)} WildDataPointers, source has {len(pointers)}")

    def rod_entries(pairs: list[tuple[int, str]]) -> list[dict]:
        rates = _even_rates(len(pairs))
        return [{"species_id": species_to_id[c], "name": id_to_name.get(species_to_id[c], c),
                 "rate": r, "min_level": lvl, "max_level": lvl}
                for r, (lvl, c) in zip(rates, pairs, strict=True)]

    old_rod_entries = rod_entries([(10, "GOLDEEN"), (10, "MAGIKARP")])  # Random&1, 50/50, both L10
    good_rod_fresh = rod_entries(good_rod_pools["GoodRodMons"])
    good_rod_ocean = rod_entries(good_rod_pools["GoodRodMonsOcean"])
    super_rod_cache = {name: rod_entries(pairs) for name, pairs in super_rod_groups.items()}

    areas: dict[str, dict] = {}
    mismatches: list[str] = []
    id_to_species = {v: k for k, v in species_to_id.items()}
    for (map_id, label), ptr in zip(pointers, rom_ptrs, strict=True):
        rom_flat = 0x2C * 0x4000 + (ptr - 0x4000)
        grass_rate, grass_slots, next_off = _rom_wild_block(rom, rom_flat)
        water_rate, water_slots, _ = _rom_wild_block(rom, next_off)

        if label != "NothingWildMons":
            path = label_to_path.get(label)
            if path is None:
                raise SystemExit(f"{title}: map {map_id}: no source asm for {label}")
            s_grass_rate, s_grass, s_water_rate, s_water = parse_map_asm(str(path), frozenset())
            if grass_rate != s_grass_rate or water_rate != s_water_rate:
                mismatches.append(f"map {map_id} {label}: rate ROM=({grass_rate},{water_rate}) "
                                  f"SRC=({s_grass_rate},{s_water_rate})")
            for kind, rom_slots, src_slots in (("grass", grass_slots, s_grass),
                                                ("water", water_slots, s_water)):
                if len(rom_slots) != len(src_slots):
                    mismatches.append(f"map {map_id} {label} {kind}: slot count "
                                      f"ROM={len(rom_slots)} SRC={len(src_slots)}")
                    continue
                for i, ((rl, rs), (sl, ssp)) in enumerate(zip(rom_slots, src_slots, strict=True)):
                    sid = species_to_id.get(ssp)
                    if rl != sl or sid is None or rs != sid:
                        mismatches.append(f"map {map_id} {label} {kind} slot{i}: "
                                          f"ROM=({rl},0x{rs:02x}/{id_to_species.get(rs)}) "
                                          f"SRC=({sl},{ssp}/{sid})")

        area_id = map_id_to_area.get(map_id)
        if not area_id:
            continue
        suffix = floor_labels.get(str(map_id), "")
        block = areas.setdefault(area_id, {})
        for method, rate, slots in (("Grass" + suffix, grass_rate, grass_slots),
                                    ("Water" + suffix, water_rate, water_slots)):
            if rate == 0 or not slots:
                continue
            entries = [(level, id_to_species.get(sp, f"$?{sp:02X}")) for level, sp in slots]
            agg = aggregate(entries, drop=("NO_MON",))
            # A byte with no known constant would already be a recorded mismatch above (and
            # raises before this function returns) -- skip it here instead of a KeyError mid-scan.
            agg = [e for e in agg if e["_const"] in species_to_id]
            method_entries = [{
                "species_id": species_to_id[e["_const"]],
                "name": id_to_name.get(species_to_id[e["_const"]], e["_const"]),
                "rate": e["rate"], "min_level": e["min_level"], "max_level": e["max_level"],
            } for e in agg]
            if method_entries:
                method_entries.sort(key=lambda x: (-x["rate"], x["species_id"]))
                block[method] = method_entries

        # Fishing: Old Rod anywhere a water table/ocean/super-rod entry says a map is fishable
        # (approximated, like W1, as no tile-level fishability scan is done here either). Good
        # Rod picks the ocean pool for an OceanMaps member, the fresh pool otherwise. Super Rod
        # only where this map has its own SuperRodData row.
        group = super_rod_group_by_map.get(map_id)
        fishable = water_rate > 0 or map_id in ocean_ids or group is not None
        if fishable:
            block["OldRod" + suffix] = old_rod_entries
            block["GoodRodOcean" + suffix if map_id in ocean_ids else "GoodRod" + suffix] = (
                good_rod_ocean if map_id in ocean_ids else good_rod_fresh)
        if group is not None:
            block["SuperRod" + suffix] = super_rod_cache[group]

        if not block:
            areas.pop(area_id, None)

    if mismatches:
        raise SystemExit(f"{title}: {len(mismatches)} ROM-vs-source mismatches:\n  " +
                         "\n  ".join(mismatches[:40]))
    return areas


def _check_rates(variant: str, areas: dict) -> list[str]:
    """Each method block must sum to 100% and carry no zero-rate species.

    A blended table shows up here immediately: extra slots push the sum past 100, and a
    species that only occupied slots in the branch we dropped lands at rate 0.
    """
    problems = []
    for area_id, block in areas.items():
        for method, entries in block.items():
            total = sum(e["rate"] for e in entries)
            if total != 100:
                problems.append(f"{variant}/{area_id}/{method}: rates sum to {total}, expected 100")
            for e in entries:
                if e["rate"] <= 0:
                    problems.append(f"{variant}/{area_id}/{method}: {e['name']} has rate {e['rate']}")
    return problems


def main_purergb() -> int:
    import argparse

    import tools.gen_gen1_area_map as area_map_gen

    ap = argparse.ArgumentParser()
    ap.add_argument("--foundation")  # consumed by the __main__ dispatcher, accepted here too
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(sys.argv[1:])

    root = gf.source_root("purergb")
    out_path, area_map_path, floor_labels_path = _purergb_out_paths()
    if not area_map_path.exists():
        sys.stderr.write(f"{area_map_path} missing -- run tools/gen_gen1_area_map.py first\n")
        return 1
    area_map = json.loads(area_map_path.read_text(encoding="utf-8"))
    floor_labels = json.loads(floor_labels_path.read_text(encoding="utf-8"))
    map_id_to_area = {int(k): v["area_id"] for k, v in area_map.items()}

    species_to_id = parse_pokemon_constants(str(root / "constants" / "pokemon_constants.asm"))
    _, name_to_map_id = area_map_gen.parse_map_constants(
        (root / "constants" / "map_constants.asm").read_text(encoding="utf-8"))

    # Slot chances: cross-check the raw /256 table cited by the plan against source text before
    # trusting the derived rate percentages built on top of it (a (b)-class source assert).
    probs_text = gf.read_source("purergb", "data/wild/probabilities.asm")
    for chance in _PURERGB_SLOT_CHANCES_256:
        needle = f"wild_chance {chance}"
        if needle not in probs_text.replace("  ", " "):
            raise SystemExit(f"probabilities.asm source assert failed: missing {needle!r}")

    names_text = gf.read_source("purergb", "data/pokemon/names.asm")
    display_names = parse_name_array(names_text, "MonsterNames")
    if len(display_names) != 190:
        raise SystemExit(f"MonsterNames: expected 190 entries, parsed {len(display_names)}")
    # names.asm stores shouting-case ("RATTATA", "NIDORAN♂"); .capitalize() is a one-line,
    # source-derived approximation of vanilla's Title Case convention -- good enough for display,
    # and it never needs a per-species override table the way a hand-typed name list would.
    id_to_name = {i + 1: n.capitalize() for i, n in enumerate(display_names)}

    ocean_names = parse_map_id_list(gf.read_source("purergb", "data/maps/ocean_maps.asm"), "OceanMaps")
    ocean_ids = {name_to_map_id[n] for n in ocean_names if n in name_to_map_id}

    good_rod_pools = parse_good_rod_pools(gf.read_source("purergb", "data/wild/good_rod.asm"))

    super_rod_text = gf.read_source("purergb", "data/wild/super_rod.asm")
    super_rod_rows = parse_super_rod_rows(super_rod_text)
    super_rod_group_by_map = {name_to_map_id[m]: g for m, g in super_rod_rows if m in name_to_map_id}
    super_rod_groups = parse_super_rod_groups(super_rod_text)

    out: dict = {"species_id_space": "internal"}
    for title in _PURERGB_TITLES:
        areas = build_purergb_title(title, root, species_to_id, id_to_name, map_id_to_area,
                                    floor_labels, ocean_ids, good_rod_pools,
                                    super_rod_group_by_map, super_rod_groups)
        problems = _check_rates(title, areas)
        if problems:
            sys.stderr.write("REFUSING TO WRITE — rate validation failed:\n")
            for p in problems[:40]:
                sys.stderr.write(f"  {p}\n")
            return 1
        out[title] = areas
        n_methods = sum(len(b) for b in areas.values())
        print(f"{title}: {len(areas)} areas, {n_methods} method tables (ROM-verified, 0 mismatches)")

    if args.check:
        if not out_path.exists() or json.loads(out_path.read_text(encoding="utf-8")) != out:
            print(f"{out_path} is stale — re-run without --check", file=sys.stderr)
            return 1
        print(f"{out_path} matches source")
        return 0

    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def main() -> int:
    for path in {repo for repo, _ in VARIANTS.values()}:
        if not os.path.exists(path):
            sys.stderr.write(f"Missing pret repo at {path}\n"
                             "Run tools/build_pret_syms.py first to clone it.\n")
            return 1

    with open(_AREA_MAP, encoding="utf-8") as f:
        area_map = json.load(f)
    with open(_SPECIES_INDEX, encoding="utf-8") as f:
        sidx = json.load(f)
    index_to_natdex = {int(k): v for k, v in sidx["index_to_national"].items()}
    map_id_to_area = {int(k): v["area_id"] for k, v in area_map.items() if isinstance(v, dict)}

    out: dict[str, dict] = {}
    problems: list[str] = []
    floor_suffixes: dict[int, str] = {}
    for variant, (repo, defines) in VARIANTS.items():
        areas, skipped_area, skipped_species, floors = build_variant(
            repo, defines, index_to_natdex, map_id_to_area)
        floor_suffixes.update(floors)
        out[variant] = areas
        problems += _check_rates(variant, areas)
        print(f"{variant}: {len(areas)} areas")
        if skipped_area:
            print(f"  {len(skipped_area)} maps skipped (no area_id mapping): "
                  + ", ".join(f"{lbl}({mid})" for mid, lbl in skipped_area))
        if skipped_species:
            print(f"  {len(skipped_species)} species skipped: {', '.join(sorted(skipped_species))}")

    if problems:
        sys.stderr.write("REFUSING TO WRITE — rate validation failed:\n")
        for p in problems[:40]:
            sys.stderr.write(f"  {p}\n")
        if len(problems) > 40:
            sys.stderr.write(f"  ... and {len(problems) - 40} more\n")
        return 1

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {_OUT} (per-variant: {', '.join(out)})")

    # Published for server/adapters/gen1_rom_scan.py, which labels a RANDOMIZED cartridge's
    # floors and must produce identical keys -- the clean-ROM control asserts the two agree.
    with open(_FLOORS_OUT, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(floor_suffixes.items())}, f, indent=2)
        f.write("\n")
    print(f"Wrote {_FLOORS_OUT} ({len(floor_suffixes)} multi-floor maps)")
    return 0


if __name__ == "__main__":
    # A light hand-rolled pre-parse, not argparse: the pret path below takes no flags at all
    # today, and giving it an argparse pass here (even one that only recognises --foundation)
    # would be a behavior change to the byte-identical vanilla output this edit must not touch.
    if "--foundation" in sys.argv and sys.argv[sys.argv.index("--foundation") + 1] == "purergb":
        sys.exit(main_purergb())
    sys.exit(main())
