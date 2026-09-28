#!/usr/bin/env python3
"""Generate data/games/gen3_exp/28877d73/expansion_encounters.json from the pinned
pokeemerald-expansion source (tag expansion/1.17.0, commit
e8bd1cd7b03fc032ea37e3ecd38b379b5d01a1e7 -- data/gen3_exp_sources.lock.json).

Card EXP-DATA-WILD (docs/gen3/CLOSEOUT_RUNBOOK.md step 5, "EXP-DATA": wild encounter tables
for the reference build, where today `encounter_table` returns None as a recorded limit). This is
a SOURCE/MODEL card: it extracts the table the pinned source DECLARES. It claims nothing about
the shipped ROM's compiled tables -- no read-back comparison was run, so the PHYSICAL half stays
OPEN. Do not quote this pack as ROM-verified.

Canonical source: src/data/wild_encounters.json, the same file the build's own
tools/wild_encounters/wild_encounters_to_header.py compiles into src/data/wild_encounters.h.
Reading the JSON *is* reading the pinned source: that .h is generated at build time and is not
checked in (absent from a checkout of e8bd1cd7).

gWildMonHeaders is the only map table here, and the only `for_maps: true` group at this pin -- the
other two are the Frontier's gBattlePyramidWildMonHeaders / gBattlePikeWildMonHeaders, which have
no `map` key and no area_id. map_group() selects by `for_maps` AND asserts the label, so a
renamed or added group fails loudly instead of silently changing what is extracted.

Slot weights are the pin's own, never this tool's. Each `fields[]` entry declares its
`encounter_rates`; the fishing entry additionally declares the rod split as `groups`
(old_rod/good_rod/super_rod over slot indexes). habitat_plan() reads the rod split from those
index lists -- it is not re-guessed as 0-1/2-4/5-9 -- and check_rates() then CROSS-CHECKS the
derived per-method rate vectors against server/adapters/gen3_frlge.py's _WILD_METHODS (the repo's
one proven weight table, citing pret src/wild_encounter.c:73-160) and refuses on any
disagreement. A fork that ever re-weights grass or re-cuts the rods therefore stops this
generator instead of shipping invented chance weights.

Map -> area_id goes through the PRE-EXISTING data/games/gen3_exp/28877d73/area_map.json
("group:num" -> area_id; owned by tools/gen_area_map.py --expansion 28877d73, READ ONLY here) --
the same table the Lua client resolves area ids from, so the pack cannot disagree with the client
about which map is which area. _check_area_map_digest() (reused from
tools/gen_gen3_exp_trainers.py) refuses when that area map was built from a different source tree
than this --src, which is what stops a stale group:num from silently pointing at the wrong area.
MAP_xxx -> "group:num" comes from tools/gen_gen3_trainers.py's map_keys(), the shared helper
tools/gen_gen3_exp_trainers.py already uses: it reads each map folder's own map.json "id", so
there is no name-normalisation guess (and none of gen_gen3_wild.py's canon() collision hazard)
between the wild table's "MAP_ROUTE101" and the group's folder name. This fork also carries
orphan map folders (map.json but in no group); map_keys() only walks the groups, so they are
structurally unreachable here and are never counted as unmapped.

Species ids are this build's own include/constants/species.h, which is a C *enum* in this fork,
not #define (tools/gen_gen3_exp_trainers.py's enum_values; tools/gen_gen3_wild.py's #define
parser returns {} here). An unresolved SPECIES_* macro is fatal, never dropped. Display names come
from Gen3ExpansionAdapter itself, so a wild row is spelled the way the rest of the board spells it.

Multiple active sets for one map take the FIRST in file order; the rest are listed in
alt_sets_skipped. This is a set-0-only projection: include/constants/vars.h defines
VAR_ALTERING_CAVE_WILD_SET and src/wild_encounter.c:GetCurrentMapWildMonHeaderId can select a
later Altering Cave set at runtime. That variable-dependent table remains outside this card.

The source's own wild_encounters_to_header.py emits #ifdef EMERALD/FIRERED/LEAFGREEN around
each entry (its WriteEncounters/WritePokemonHeaders). The reference build uses EMERALD. We invoke
that pinned assembler into memory and retain only entries whose mon declarations it emits inside
an active EMERALD block; FR/LG source variants do not become Emerald encounters merely because
their map id exists in this expansion area map.

Why the aggregation is not Gen3Adapter._rom_encounter_tables: that helper resolves its area map
from its own `title`/`self._rom_type`, which can only ever be the vanilla FRLG or the vanilla
Emerald pack. This build numbers its own groups (Hoenn in group 0, Kanto in 35/36/37) and shares
no key with either, so calling it would file Kanto's Route 21 under some Hoenn name. The
first-wins-per-area-and-method reduction is therefore repeated here against THIS build's area map
and pinned by tests/unit/test_gen3_expansion_wild.py, which re-derives it from the pin
independently. The right follow-up is one parameter on _rom_encounter_tables (area map in, no
behaviour change) and deleting this copy; that is shared-adapter work and deliberately not in this
card.

Limits, each checked at this pin, none of them a guess:
  * include/config/wild_encounter.h:20 -- WE_OW_ENCOUNTERS is FALSE, so Overworld Wild Encounters
    are compiled out and gWildMonHeaders is the whole map wild story. An OWE build would spawn
    species this pack has no table for. WE_FLAG_NO_ENCOUNTER is 0.
  * include/config/overworld.h:95 -- OW_TIME_OF_DAY_ENCOUNTERS is FALSE, so one table per map and
    no Morn/Day/Nite split. The build's header still carries
    encounterTypes[TIMES_OF_DAY_COUNT] (include/wild_encounter.h:44) with TIME_MORNING as the
    fallback; the JSON carries no time-suffixed base_labels, so the fallback table is the only one.
  * include/wild_encounter.h:32-38 -- struct WildEncounterTypes has a FIFTH pointer,
    hiddenMonsInfo, that vanilla does not have. This pin's JSON declares no hidden habitat, so the
    build's own header tool (ParseMonTypes, which enumerates the JSON's field types) never emits
    one and the pointer is NULL. habitat_plan() refuses on an unlabelled habitat rather than
    dropping a table it cannot present.
  * gWildFeebas, Sootopolis' legendary-encounter check (AreLegendariesInSootopolisPreventingEncounters)
    and the map scripts' fixed encounters are runtime species overrides, not rate tables. They are
    out of this card's scope and are NOT represented here.

    python tools/gen_gen3_exp_wild.py --src <expansion-checkout>           # regenerate
    python tools/gen_gen3_exp_wild.py --src <expansion-checkout> --check   # exit 1 if stale
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.adapters import gen3_frlge  # noqa: E402
from server.adapters.gen3_expansion import ROM_TYPE, Gen3ExpansionAdapter  # noqa: E402
from tools.gen_gen3_exp_trainers import _check_area_map_digest, enum_values  # noqa: E402
from tools.gen_gen3_trainers import map_keys, read  # noqa: E402

OUT_JSON = ROOT / "data/games/gen3_exp/28877d73/expansion_encounters.json"
AREA_MAP = ROOT / "data/games/gen3_exp/28877d73/area_map.json"
LOCK = ROOT / "data/gen3_exp_sources.lock.json"
WILD_JSON = "src/data/wild_encounters.json"
MAP_GROUP_LABEL = "gWildMonHeaders"

# A habitat with no `groups` is ONE method that consumes all of its slots in order; a habitat WITH
# `groups` (fishing) is split by the declared slot indexes -- that is where the rods come from.
# The labels are the vocabulary the rest of the server already uses, and check_rates() below
# refuses to run unless they (and the rates) match gen3_frlge._WILD_METHODS exactly, so this dict
# is checked input, not a second source of method names.
UNGROUPED_LABELS = {"land_mons": "Grass", "water_mons": "Surfing",
                    "rock_smash_mons": "Rock Smash"}


def git_head(path: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def tracked_changes(path: Path) -> str:
    """Tracked edits at the pinned HEAD would make the source claim false."""
    r = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"cannot check tracked source status at {path}: {r.stderr.strip()}")
    return r.stdout.strip()


def pinned_commit() -> str:
    """The one pin, read from the lock -- never a second copy of the sha in this module."""
    return json.loads(read(LOCK))["source"]["commit"]


def map_group(data: dict) -> dict:
    """The single `for_maps` group: the map wild table, by label as well as by flag."""
    for_maps = [g for g in data["wild_encounter_groups"] if g.get("for_maps")]
    labels = [g.get("label") for g in for_maps]
    if labels != [MAP_GROUP_LABEL]:
        raise SystemExit(f"{WILD_JSON}: expected exactly one for_maps group named "
                         f"{MAP_GROUP_LABEL!r}, got {labels} -- refusing to guess which table "
                         "this build ships")
    return for_maps[0]


def habitat_plan(fields: list) -> list[tuple[str, list[tuple[str, tuple[int, ...]]]]]:
    """[(habitat, [(method_label, slot_rates), ...]), ...] from the pin's own `fields` block.

    The `groups` index lists must be ascending runs that partition the declared slots exactly
    once; anything else means the rod split in the source and the slot order this tool assumes
    have drifted, so it refuses rather than emit a plausible-looking rod table.
    """
    out = []
    for field in fields:
        habitat = field["type"]
        rates = tuple(int(r) for r in field["encounter_rates"])
        groups = field.get("groups")
        if not groups:
            label = UNGROUPED_LABELS.get(habitat)
            if label is None:
                raise SystemExit(f"{WILD_JSON}: habitat {habitat!r} declares no `groups` and has no "
                                 f"method label in {sorted(UNGROUPED_LABELS)} -- refusing to "
                                 "invent one")
            out.append((habitat, [(label, rates)]))
            continue
        methods, taken = [], []
        for name in groups:                       # the source file's own order
            indexes = [int(i) for i in groups[name]]
            if indexes != sorted(indexes) or len(set(indexes)) != len(indexes):
                raise SystemExit(f"{habitat}.{name}: slot indexes {indexes} are not an ascending "
                                 "run -- the split would not be contiguous")
            taken += indexes
            label = " ".join(word.capitalize() for word in name.split("_"))
            methods.append((label, tuple(rates[i] for i in indexes)))
        if sorted(taken) != list(range(len(rates))):
            raise SystemExit(f"{habitat}: `groups` indexes {sorted(taken)} do not partition the "
                             f"{len(rates)} declared slot rates {list(rates)}")
        out.append((habitat, methods))
    return out


def check_rates(plan) -> None:
    """Refuse unless the pin's own per-method rate vectors equal the repo's proven weights.

    _WILD_METHODS (server/adapters/gen3_frlge.py) is the single table of Gen 3 slot weights in
    this repo, transcribed from pret src/wild_encounter.c:73-160. Comparing the pin against it
    is what makes "the weights are the source's" checkable rather than merely asserted.
    """
    want = {(habitat, method): tuple(rates)
            for habitat, methods in gen3_frlge._WILD_METHODS
            for method, rates in methods}
    # The pin names its habitats "<habitat>_mons" and _WILD_METHODS names them bare; compare the
    # bare habitat, or every lookup would miss and every run would refuse.
    got = {(habitat.removesuffix("_mons"), method): rates
           for habitat, methods in plan
           for method, rates in methods}
    if got != want:
        raise SystemExit(
            "this pin's declared slot weights differ from the repo's proven table "
            "(server/adapters/gen3_frlge.py _WILD_METHODS):\n"
            f"  pin:    {sorted(got.items())}\n  proven: {sorted(want.items())}\n"
            "refusing to ship invented chance weights -- reconcile the two first")


def emerald_compiled_labels(src: Path, data: dict, group: dict) -> set[str]:
    """Use the pinned build's header assembler to identify EMERALD-active wild entries."""
    makefile = read(src / "Makefile")
    if not re.search(r"(?m)^GAME_VERSION\s*\?=\s*EMERALD\s*$", makefile):
        raise SystemExit("reference build is no longer Makefile's EMERALD default")
    tool = src / "tools/wild_encounters/wild_encounters_to_header.py"
    spec = importlib.util.spec_from_file_location("pinned_wild_header", tool)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load pinned wild header assembler: {tool}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.Config(src / "include/config/overworld.h", src / "include/constants/rtc.h", data)
    emitted = io.StringIO()
    module.WildEncounterAssembler(emitted, data, config).WriteEncounters()
    active, declarations = [], set()
    for line in emitted.getvalue().splitlines():
        stripped = line.strip()
        if stripped.startswith("#ifdef "):
            active.append(stripped.removeprefix("#ifdef ") == "EMERALD")
        elif stripped == "#endif":
            if not active:
                raise SystemExit("pinned wild header has unmatched #endif")
            active.pop()
        elif active and all(active):
            match = re.match(r"const struct WildPokemon (\w+)\[\] =", stripped)
            if match:
                declarations.add(match.group(1))
    if active:
        raise SystemExit("pinned wild header has unterminated #ifdef")
    habitats = {field["type"] for field in group["fields"]}
    labels = {entry["base_label"] for entry in group["encounters"]
              if any(f"{entry['base_label']}_{habitat.title().replace('_', '')}" in declarations
                     for habitat in habitats if habitat in entry)}
    if not labels:
        raise SystemExit("pinned header assembler emitted no EMERALD-active map wild tables")
    return labels


def build_wild(src: Path, plan, positions: dict[str, tuple[int, int]]
               , active_labels: set[str]) -> tuple[dict, list[str], list[str]]:
    """src/data/wild_encounters.json -> {(group, num): {method: [(rate, mon), ...]}}: the exact
    shape gen3_rom_tables.decode_wild_encounters() produces from a live ROM, so the reduction
    below is the one that already runs for randomized carts and RR. Returns (wild, unmapped map
    ids, skipped later sets for a map)."""
    group = map_group(json.loads(read(src / WILD_JSON)))
    wild: dict = {}
    unmapped: list[str] = []
    alt_sets: list[str] = []
    for entry in group["encounters"]:
        if entry["base_label"] not in active_labels:
            continue
        pos = positions.get(entry["map"])
        if pos is None:
            unmapped.append(entry["map"])
            continue
        if pos in wild:
            alt_sets.append(entry["map"])       # a later set for the same map: not "set 0"
            continue
        block = {}
        for habitat, methods in plan:
            table = entry.get(habitat)
            if table is None:
                continue
            mons = table["mons"]
            want = sum(len(rates) for _, rates in methods)
            if len(mons) != want:
                raise SystemExit(f"{entry['map']} {habitat}: {len(mons)} mons for {want} declared "
                                 f"slot rates -- the source's own table is inconsistent")
            offset = 0
            for method, rates in methods:
                block[method] = [(rate, mons[offset + i]) for i, rate in enumerate(rates)]
                offset += len(rates)
        wild[pos] = block
    return wild, unmapped, alt_sets


def aggregate(wild: dict, area_map: dict, species: dict[str, int], species_name) -> dict:
    """{(group, num), methods} -> area_id -> method -> entries.

    First (map group, map num) wins per area AND per method -- the rule
    Gen3Adapter._rom_encounter_tables applies to a live ROM: a dungeon spread over several maps
    contributes every method it has (Mt. Moon's grass and water come from different maps), and a
    second map never overwrites the first map's method. Positions sort as ints, not as the
    "group:num" strings, so 0:10 does not sort before 0:2.
    """
    out: dict = {}
    for pos in sorted(wild):
        area_id = area_map.get(f"{pos[0]}:{pos[1]}")
        if not area_id:
            continue
        block = out.setdefault(area_id, {})
        for method, slots in wild[pos].items():
            if method in block:
                continue
            agg: dict = {}
            for rate, mon in slots:
                sp = species.get(mon["species"])
                if sp is None:
                    raise SystemExit(f"{mon['species']} is not in include/constants/species.h -- "
                                     "refusing to drop or guess a wild slot's species")
                entry = agg.setdefault(sp, {"species_id": sp, "name": species_name(sp),
                                            "rate": 0, "min_level": mon["min_level"],
                                            "max_level": mon["max_level"]})
                entry["rate"] += rate
                entry["min_level"] = min(entry["min_level"], mon["min_level"])
                entry["max_level"] = max(entry["max_level"], mon["max_level"])
            block[method] = sorted(agg.values(), key=lambda e: (-e["rate"], e["species_id"]))
    return {area: block for area, block in out.items() if block}


def _check_map_keys_unique(src: Path, keys: dict[str, str]) -> None:
    """map_keys() is keyed by each folder's own map.json "id", so two folders claiming one id
    would silently collapse into one position. Compare its size against the raw slot count."""
    groups = json.loads(read(src / "data/maps/map_groups.json"))
    slots = sum(len(groups[name]) for name in groups["group_order"])
    if len(keys) != slots:
        raise SystemExit(f"data/maps/map_groups.json has {slots} slots but only {len(keys)} "
                         "distinct MAP_ ids -- a duplicate map.json id would merge two maps")


def build(src: Path, area_map_path: Path = AREA_MAP) -> dict:
    """Return the expansion_encounters.json dict."""
    # Refuse a stale area map before anything reads "group:num" (see _check_area_map_digest).
    _check_area_map_digest(src, area_map_path)
    wild_data = json.loads(read(src / WILD_JSON))
    group = map_group(wild_data)
    plan = habitat_plan(group["fields"])
    check_rates(plan)
    species = enum_values(read(src / "include/constants/species.h"), "SPECIES_")
    if not species:
        raise SystemExit("include/constants/species.h yielded no SPECIES_ values -- this fork "
                         "uses a C enum, so a #define parser would silently return {} here")
    keys = map_keys(src)
    _check_map_keys_unique(src, keys)
    positions = {map_id: tuple(int(part) for part in key.split(":"))
                 for map_id, key in keys.items()}
    wild, unmapped, alt_sets = build_wild(src, plan, positions,
                                         emerald_compiled_labels(src, wild_data, group))
    area_map = json.loads(read(area_map_path))
    # A map that resolved a position but whose group:num has no area_map.json entry is dropped by
    # the reduction; name it rather than losing it quietly (same reporting gen_gen3_wild.py does).
    map_of = {pos: map_id for map_id, pos in positions.items()}
    for pos in sorted(wild):
        if f"{pos[0]}:{pos[1]}" not in area_map:
            unmapped.append(map_of[pos])
    encounters = aggregate(wild, area_map, species,
                           Gen3ExpansionAdapter(rom_type=ROM_TYPE).species_name)
    lock = json.loads(read(LOCK))["source"]
    return {
        "_note": "GENERATED by tools/gen_gen3_exp_wild.py from pokeemerald-expansion "
                 "src/data/wild_encounters.json -- do not edit. area_id -> method -> "
                 "[{species_id, name, rate, min_level, max_level}, ...], the same shape as a "
                 "randomized cartridge's ingested table, RR's rr_encounters.json and the vanilla "
                 "Gen 3 packs. Extracted from the pinned SOURCE; not read back from the ROM.",
        "source": {"repo": lock["url"].removeprefix("https://github.com/").removesuffix(".git"),
                   "tag": lock["tag"], "commit": lock["commit"]},
        "title": ROM_TYPE,
        "unmapped_maps": sorted(set(unmapped)),
        "alt_sets_skipped": sorted(set(alt_sets)),
        "encounters": dict(sorted(encounters.items())),
    }


def dump(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, required=True,
                    help="checkout of the pinned expansion source tree; git rev-parse HEAD must "
                         "equal data/gen3_exp_sources.lock.json")
    ap.add_argument("--area-map", type=Path, default=AREA_MAP)
    ap.add_argument("--out", type=Path, default=OUT_JSON)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if --out differs from a regeneration")
    a = ap.parse_args()
    if not a.src.exists():
        print(f"source not found: {a.src}", file=sys.stderr)
        return 2
    pin = pinned_commit()
    head = git_head(a.src)
    # The area-map digest check below binds map_groups.json + wild_encounters.json, but NOT
    # include/constants/species.h -- the file every species id in the pack comes from. A checkout
    # at another commit would therefore pass that digest and ship wrong ids, so the pin is checked
    # directly. A plain directory copy (no .git) is refused for the same reason: say so rather than
    # claim a pin nothing verified.
    if head != pin:
        print(f"{a.src} is at {head or 'not a git checkout'}, not the pin {pin} ({LOCK})",
              file=sys.stderr)
        return 2
    dirty = tracked_changes(a.src)
    if dirty:
        print(f"{a.src} has dirty tracked source at pinned HEAD ({dirty}); refusing to label "
              f"generated data as {pin}", file=sys.stderr)
        return 2
    text = dump(build(a.src, a.area_map))
    if a.check:
        if not a.out.exists() or a.out.read_text(encoding="utf-8") != text:
            print(f"{a.out} is stale -- re-run tools/gen_gen3_exp_wild.py", file=sys.stderr)
            return 1
        print(f"{a.out.name} is up to date")
        return 0
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
