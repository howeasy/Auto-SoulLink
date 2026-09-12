#!/usr/bin/env python3
"""Generate Gen 1 wild encounter tables from pret/pokered raw asm.

Reads:
    .cache/pret/pokered/data/wild/grass_water.asm          (map_id → label)
    .cache/pret/pokered/data/wild/maps/*.asm               (per-map encounter slots)
    .cache/pret/pokered/data/wild/good_rod.asm             (Good Rod: two global entries)
    .cache/pret/pokered/data/wild/super_rod.asm            (Super Rod: per-map groups)
    .cache/pret/pokered/engine/items/item_effects.asm      (Old Rod: `lb bc, 5, MAGIKARP`)
    .cache/pret/pokered/constants/pokemon_constants.asm    (species name → internal idx)
    data/games/gen1_rby/area_map.json                      (map_id → area_id)
    data/games/gen1_rby/species_index.json                 (internal idx → NatDex)

Writes:
    data/games/gen1_rby/encounter_tables.json

Slot percentages per pret/data/wild/probabilities.asm:
    slot 0,1: 20%   slot 2: 15%   slots 3-5: 10%   slots 6-7: 5%   slot 8: 4%   slot 9: 1%

Per-species rates are summed across all slots the species occupies.
Min/max levels are min/max across those slots.

Fishing. Old Rod is one entry at 100%, Good Rod two entries at 50% each; both are global
in the ROM and are placed under EVERY area that has a Water (surf) method on any floor or a
Super Rod group -- one rule, applied to all three titles. Super Rod is per map, picked
uniformly by the game (ReadSuperRodData rerolls a 2-bit number until it is below the group
size), so its 2-4 entries share 100% equally through the scanner's own `uniform_rates`, and
a clean cartridge scanned at runtime reproduces this file. Like the scanner, Super Rod
carries no floor suffix and the lowest map id wins within an area. Old and Good Rod are
generator-only: the scanner does not emit them.

    python tools/gen_gen1_encounters.py          # regenerate
    python tools/gen_gen1_encounters.py --check  # rebuild in memory and diff (exit 1 on drift)
"""
from __future__ import annotations

import json
import os
import re
import sys

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


def aggregate(entries: list[tuple[int, str]], rates: list[int] = SLOT_RATES) -> list[dict]:
    """Collapse a slot list to per-species rate + min/max levels.

    Drops MISSINGNO entries (species_const == "MISSINGNO") and NO_MON.
    """
    by_species: dict[str, dict] = {}
    for slot, (level, sp) in enumerate(entries):
        if sp in ("NO_MON", "MISSINGNO"):
            continue
        rate = rates[slot] if slot < len(rates) else 0
        if sp not in by_species:
            by_species[sp] = {"_const": sp, "rate": 0, "min_level": level, "max_level": level}
        cur = by_species[sp]
        cur["rate"] += rate
        cur["min_level"] = min(cur["min_level"], level)
        cur["max_level"] = max(cur["max_level"], level)
    return list(by_species.values())


def parse_map_constants(path: str) -> dict[str, int]:
    """MAP_NAME -> map id, in `map_const` order (Gen 1 has no skips)."""
    out: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^\s*map_const\s+([A-Z_0-9]+)\s*,", line)
            if m:
                out[m.group(1)] = len(out)
    return out


def parse_old_rod(repo: str) -> list[tuple[int, str]]:
    """ItemUseOldRod's `lb bc, LEVEL, SPECIES` -- the only such line in item_effects.asm."""
    path = os.path.join(repo, "engine", "items", "item_effects.asm")
    with open(path, encoding="utf-8") as f:
        found = re.findall(r"^\s*lb\s+bc\s*,\s*(\d+)\s*,\s*([A-Z][A-Z_0-9]*)\s*$", f.read(), re.M)
    if len(found) != 1:
        raise ValueError(f"{path}: expected one `lb bc, level, SPECIES`, found {found}")
    return [(int(found[0][0]), found[0][1])]


def parse_good_rod(repo: str) -> list[tuple[int, str]]:
    """GoodRodMons: `db level, SPECIES` x2."""
    out = []
    with open(os.path.join(repo, "data", "wild", "good_rod.asm"), encoding="utf-8") as f:
        for raw in f:
            m = re.match(r"^\s*db\s+(\d+)\s*,\s*([A-Z_0-9]+)", raw.split(";", 1)[0])
            if m:
                out.append((int(m.group(1)), m.group(2)))
    if len(out) != 2:
        raise ValueError(f"good_rod.asm: expected 2 entries, found {out}")
    return out


def parse_super_rod(repo: str, map_consts: dict[str, int]) -> dict[int, list[tuple[int, str]]]:
    """map id -> [(level, SPECIES)], in file order.

    pokered: `dbw MAP, .GroupN` pointers, then `.GroupN:` / `db count` / `db level, SPECIES`.
    pokeyellow: one flat row per map, `db MAP, SPECIES, level, SPECIES, level, ...`.
    """
    per_map: dict[int, list[tuple[int, str]]] = {}
    pointers: dict[int, str] = {}
    groups: dict[str, list[tuple[int, str]]] = {}
    cur: str | None = None
    with open(os.path.join(repo, "data", "wild", "super_rod.asm"), encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            m = re.match(r"^dbw\s+([A-Z_0-9]+)\s*,\s*(\.[A-Za-z0-9_]+)\s*$", line)
            if m:
                pointers[map_consts[m.group(1)]] = m.group(2)
                continue
            m = re.match(r"^(\.[A-Za-z0-9_]+):\s*$", line)
            if m:
                cur = m.group(1)
                groups[cur] = []
                continue
            m = re.match(r"^db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", line)
            if m and cur is not None:
                groups[cur].append((int(m.group(1)), m.group(2)))
                continue
            m = re.match(r"^db\s+([A-Z_0-9]+)\s*,\s*(.+)$", line)
            if m and m.group(1) in map_consts:
                fields = [x.strip() for x in m.group(2).split(",")]
                per_map[map_consts[m.group(1)]] = [
                    (int(fields[i + 1]), fields[i]) for i in range(0, len(fields), 2)]
    for map_id, label in pointers.items():
        per_map[map_id] = groups[label]
    for map_id, entries in per_map.items():
        if not entries:
            raise ValueError(f"super_rod.asm: map {map_id} has an empty group")
    return per_map


def super_rod_rates(entries: list[tuple[int, str]]) -> list[int]:
    """Uniform per-entry percentages: the game rerolls a 2-bit number until it is below the
    group size (ReadSuperRodData), so every entry is equally likely. Shared with the ROM
    scanner so a clean cartridge reproduces this file exactly."""
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)
    from server.adapters.gen1_rom_scan import uniform_rates
    return list(uniform_rates(len(entries)))


def build_variant(repo: str, defines: frozenset[str], index_to_natdex: dict[int, int],
                  map_id_to_area: dict[int, str]) -> tuple[dict, list, set]:
    """Encounter tables for ONE game version. Returns (areas, skipped_areas, skipped_species)."""
    species_consts = parse_pokemon_constants(
        os.path.join(repo, "constants", "pokemon_constants.asm")
    )
    pointers = parse_wild_pointers(os.path.join(repo, "data", "wild", "grass_water.asm"))
    skipped_unknown_species: set[str] = set()

    def to_entries(agg: list[dict]) -> list[dict]:
        """Aggregated species consts -> the JSON entry shape, most likely first."""
        out = []
        for e in agg:
            idx = species_consts.get(e["_const"])
            natdex = index_to_natdex.get(idx) if idx is not None else None
            if not natdex:
                skipped_unknown_species.add(e["_const"])
                continue
            out.append({
                "species_id": natdex,
                "name": species_display_name(e["_const"]),
                "rate": e["rate"],
                "min_level": e["min_level"],
                "max_level": e["max_level"],
            })
        out.sort(key=lambda x: (-x["rate"], x["species_id"]))
        return out

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
            method_entries = to_entries(aggregate(entries))
            if method_entries:
                block[method] = method_entries
        if not block:
            areas.pop(area_id, None)

    # FISHING. Super Rod is per map: no floor suffix and lowest map id wins within an area,
    # exactly as gen1_rom_scan.build_encounter_tables adds it, so the clean-ROM control
    # holds for it too. Old and Good Rod are global in the ROM, so the placement rule is
    # ours: every area with a Water method on any floor, or a Super Rod group, gets both.
    super_rod = parse_super_rod(repo, parse_map_constants(
        os.path.join(repo, "constants", "map_constants.asm")))
    fishing_areas: list[str] = [a for a, b in areas.items()
                                if any(m.startswith("Water") for m in b)]
    for map_id in sorted(super_rod):
        area_id = map_id_to_area.get(map_id)
        if not area_id:
            skipped_unknown_area.append((map_id, "SuperRod"))
            continue
        block = areas.setdefault(area_id, {})
        if area_id not in fishing_areas:
            fishing_areas.append(area_id)
        if "Super Rod" not in block:
            block["Super Rod"] = to_entries(aggregate(super_rod[map_id], super_rod_rates(super_rod[map_id])))
    old_rod = to_entries(aggregate(parse_old_rod(repo), [100]))
    good_rod = to_entries(aggregate(parse_good_rod(repo), [50, 50]))
    for area_id in fishing_areas:
        areas[area_id]["Old Rod"] = list(old_rod)
        areas[area_id]["Good Rod"] = list(good_rod)

    return areas, skipped_unknown_area, skipped_unknown_species, floor_suffix_by_map


# variant -> (repo path, rgbasm defines). Yellow is its own decomp and has no conditionals.
VARIANTS = {
    "red":    (_PRET, frozenset({"_RED"})),
    "blue":   (_PRET, frozenset({"_BLUE"})),
    "yellow": (_PRET_YELLOW, frozenset()),
}


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


def build(quiet: bool = False) -> tuple[dict, dict[str, str], list[str]]:
    """(tables, floor_suffixes, problems) for all three titles, from the decomps."""
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
        if quiet:
            continue
        rods = {r: sum(1 for b in areas.values() if r in b)
                for r in ("Old Rod", "Good Rod", "Super Rod")}
        print(f"{variant}: {len(areas)} areas; rod methods {rods}")
        if skipped_area:
            print(f"  {len(skipped_area)} maps skipped (no area_id mapping): "
                  + ", ".join(f"{lbl}({mid})" for mid, lbl in skipped_area))
        if skipped_species:
            print(f"  {len(skipped_species)} species skipped: {', '.join(sorted(skipped_species))}")
    return out, {str(k): v for k, v in sorted(floor_suffixes.items())}, problems


def diff_against_shipped(out: dict, floor_suffixes: dict[str, str]) -> list[str]:
    """First differences between an in-memory rebuild and the two shipped files."""
    diffs: list[str] = []
    try:
        with open(_OUT, encoding="utf-8") as f:
            shipped = json.load(f)
        with open(_FLOORS_OUT, encoding="utf-8") as f:
            shipped_floors = json.load(f)
    except (OSError, ValueError) as exc:
        return [f"cannot read shipped file: {exc}"]
    if shipped_floors != floor_suffixes:
        diffs.append(f"floor_labels.json differs: {shipped_floors} != {floor_suffixes}")
    for variant in sorted(set(out) | set(shipped)):
        built, have = out.get(variant, {}), shipped.get(variant, {})
        for area in sorted(set(built) | set(have)):
            for method in sorted(set(built.get(area, {})) | set(have.get(area, {}))):
                b, h = built.get(area, {}).get(method), have.get(area, {}).get(method)
                if b != h:
                    diffs.append(f"{variant}/{area}/{method}: built {b} != shipped {h}")
    return diffs


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for path in {repo for repo, _ in VARIANTS.values()}:
        if not os.path.exists(path):
            sys.stderr.write(f"Missing pret repo at {path}\n"
                             "Run tools/build_pret_syms.py first to clone it.\n")
            return 1

    out, floor_suffixes, problems = build()

    if problems:
        sys.stderr.write("REFUSING TO WRITE — rate validation failed:\n")
        for p in problems[:40]:
            sys.stderr.write(f"  {p}\n")
        if len(problems) > 40:
            sys.stderr.write(f"  ... and {len(problems) - 40} more\n")
        return 1

    if "--check" in argv:
        diffs = diff_against_shipped(out, floor_suffixes)
        if diffs:
            print(f"DRIFT: {len(diffs)} difference(s) between pret and {_OUT}")
            for d in diffs[:20]:
                print(f"  {d}")
            return 1
        print(f"OK: encounter_tables.json matches pret for {', '.join(out)}")
        return 0

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {_OUT} (per-variant: {', '.join(out)})")

    # Published for server/adapters/gen1_rom_scan.py, which labels a RANDOMIZED cartridge's
    # floors and must produce identical keys -- the clean-ROM control asserts the two agree.
    with open(_FLOORS_OUT, "w", encoding="utf-8") as f:
        json.dump(floor_suffixes, f, indent=2)
        f.write("\n")
    print(f"Wrote {_FLOORS_OUT} ({len(floor_suffixes)} multi-floor maps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
