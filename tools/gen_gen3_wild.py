#!/usr/bin/env python3
"""Generate vanilla Gen 3 wild-encounter tables from pinned pret source: FireRed and LeafGreen
(from pokefirered's src/data/wild_encounters.json, which packs both titles into one file, base
label suffixed _FireRed/_LeafGreen) and Emerald (from pokeemerald's own copy).

Reuses the SAME aggregation the randomized/live-ROM path already uses
(Gen3Adapter._rom_encounter_tables, server/adapters/gen3_frlge.py): we build the pret JSON into
the exact {(map_group, map_num): [habitats, ...]} shape decode_wild_encounters() would produce
from a live ROM, then hand it to that one function. One code path, one output shape, for the
clean, randomized and RR sources alike -- clean carts just source `wild` from pret's JSON instead
of ROM bytes.

Map -> area_id goes through data/maps/map_groups.json (name -> (group, map_num), the same
group_order/array-position pret's build derives the numeric ids from) and the adapter's own
area_map.json (group:num -> area_id, already used by the randomized-ingest path). A map with
wild encounters but no area_map entry is skipped and reported (never invented).

Species are pret's own SPECIES_* constants (include/constants/species.h) -- the same ints
Gen3Adapter.species_name()/calc_species() already take, matching the RR and randomized-ingest
species encoding.

Altering Cave (and similarly repointed maps) ships several alternate wild-mon sets for the same
map; only VAR_ALTERING_CAVE_WILD_SET picks the active one at runtime, so -- exactly like the
randomized-ingest path -- we take the FIRST set in file order ("set 0").

    python tools/gen_gen3_wild.py [--game firered|leafgreen|emerald]           # regenerate
    python tools/gen_gen3_wild.py [--game firered|leafgreen|emerald] --check   # exit 1 if stale
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.adapters.gen3_frlge import Gen3Adapter  # noqa: E402

LOCK = ROOT / "data/gen3_sources.lock.json"
EMERALD_PROVENANCE = ROOT / "data/gen3/pret/pokeemerald_provenance.json"

GAMES = {
    "firered": {
        "repo": "pret/pokefirered", "clone": "pokefirered", "env": "SLINK_PRET_FIRERED_SRC",
        "pin": lambda: json.loads(read(LOCK))["source"]["commit"],
        "wild_json": "src/data/wild_encounters.json",
        "title_suffix": "FireRed", "rom_type": "firered",
        "out": ROOT / "data/games/gen3_frlge/firered_encounters.json",
    },
    "leafgreen": {
        "repo": "pret/pokefirered", "clone": "pokefirered", "env": "SLINK_PRET_FIRERED_SRC",
        "pin": lambda: json.loads(read(LOCK))["source"]["commit"],
        "wild_json": "src/data/wild_encounters.json",
        "title_suffix": "LeafGreen", "rom_type": "leafgreen",
        "out": ROOT / "data/games/gen3_frlge/leafgreen_encounters.json",
    },
    "emerald": {
        "repo": "pret/pokeemerald", "clone": "pokeemerald", "env": "SLINK_PRET_EMERALD_SRC",
        "pin": lambda: json.loads(read(EMERALD_PROVENANCE))["origin"]["source_commit"],
        "wild_json": "src/data/wild_encounters.json",
        "title_suffix": None, "rom_type": "emerald",
        "out": ROOT / "data/games/gen3_emerald/emerald_encounters.json",
    },
}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def find_pret(env=os.environ, game: str = "firered") -> Path:
    g = GAMES[game]
    if env.get(g["env"]):
        return Path(env[g["env"]])
    rel = f".cache/pret/{g['clone']}"
    return next((d / rel for d in (ROOT, *ROOT.parents) if (d / rel).exists()), ROOT / rel)


def git_head(path: Path) -> str | None:
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def defines(text: str, prefix: str) -> dict[str, int]:
    return {m[0]: int(m[1], 0) for m in re.findall(rf"#define\s+({prefix}\w+)\s+(\w+)\b", text)
            if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", m[1])}


def map_positions(root: Path) -> dict[str, tuple[int, int]]:
    """canon(map display name) -> (map_group, map_num): position in data/maps/map_groups.json's
    group_order/per-group arrays, the same numbering pret's build assigns MAP_GROUP()/MAP_NUM()
    and the client's `bank:map` area_map.json keys use."""
    d = json.loads(read(root / "data/maps/map_groups.json"))
    out: dict[str, tuple[int, int]] = {}
    for gi, grp in enumerate(d["group_order"]):
        for mi, name in enumerate(d[grp]):
            out[canon(name)] = (gi, mi)
    return out


_HABITATS = (("land_mons", "land"), ("water_mons", "water"),
             ("rock_smash_mons", "rock_smash"), ("fishing_mons", "fishing"))


def build_wild(root: Path, wild_json: str, title_suffix: str | None,
               species: dict[str, int], positions: dict[str, tuple[int, int]]
               ) -> tuple[dict[tuple[int, int], list[dict]], list[str]]:
    """pret's src/data/wild_encounters.json -> {(map_group, map_num): [habitats, ...]}, the exact
    shape gen3_rom_tables.decode_wild_encounters() produces from a live ROM (habitats: land/water/
    rock_smash/fishing -> None or {"rate": int, "mons": [{"species": int, "min_level", "max_level"}]}),
    so Gen3Adapter._rom_encounter_tables can aggregate it unchanged. First entry per map wins
    (file/ROM order) -- Altering Cave's "set 0". Returns (wild, unmapped map names)."""
    data = json.loads(read(root / wild_json))
    encs = data["wild_encounter_groups"][0]["encounters"]
    wild: dict[tuple[int, int], list[dict]] = {}
    unmapped: list[str] = []
    for e in encs:
        if title_suffix and not e["base_label"].endswith("_" + title_suffix):
            continue
        pos = positions.get(canon(e["map"][4:]))
        if pos is None:
            unmapped.append(e["map"])
            continue
        if pos in wild:
            continue  # a later set for the same map in file order: not "set 0"
        habitats = {}
        for key, habitat in _HABITATS:
            block = e.get(key)
            habitats[habitat] = None if block is None else {
                "rate": block["encounter_rate"],
                "mons": [{"species": species[m["species"]], "min_level": m["min_level"],
                          "max_level": m["max_level"]} for m in block["mons"]],
            }
        wild[pos] = [habitats]
    return wild, unmapped


def build(root: Path, game: str) -> dict:
    from server.adapters.gen3_frlge import _emerald_json, _frlg_area_map

    g = GAMES[game]
    species = defines(read(root / "include/constants/species.h"), "SPECIES_")
    positions = map_positions(root)
    wild, unmapped = build_wild(root, g["wild_json"], g["title_suffix"], species, positions)
    area_map = _emerald_json("area_map.json") if g["rom_type"] == "emerald" else _frlg_area_map()
    # Maps that resolved a (group, map_num) position but that position has no area_map.json
    # entry: _rom_encounter_tables silently drops these (area_map.get(...) is None), so they
    # never surface in `encounters` -- report them by name instead of losing them quietly.
    by_pos = {pos: name for name, pos in positions.items()}
    for pos in wild:
        if "{}:{}".format(*pos) not in area_map:
            unmapped.append(by_pos.get(pos, str(pos)))
    adapter = Gen3Adapter(is_rr=False, rom_type=g["rom_type"])
    encounters = adapter._rom_encounter_tables(wild)  # same aggregation as the ROM/randomized path
    return {
        "_note": f"GENERATED by tools/gen_gen3_wild.py from {g['repo']} -- do not edit. "
                 "area_id -> method -> [{{species_id, name, rate, min_level, max_level}}, ...], "
                 "the same shape as a randomized cartridge's ingested table or RR's rr_encounters.json.",
        "source": {"repo": g["repo"], "commit": git_head(root)},
        "title": g["rom_type"],
        "unmapped_maps": sorted(set(unmapped)),
        "encounters": dict(sorted(encounters.items())),
    }


def dump(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", choices=sorted(GAMES), default=None,
                     help="default: regenerate all three")
    ap.add_argument("--pret", type=Path, default=None, help="pret checkout (default: the pinned clone)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="exit 1 if --out differs from a regeneration")
    a = ap.parse_args()
    games = [a.game] if a.game else sorted(GAMES)
    status = 0
    for game in games:
        g = GAMES[game]
        out = a.out or g["out"]
        root = a.pret or find_pret(game=game)
        if not root.exists():
            print(f"pret source not found: {root} (set {g['env']})", file=sys.stderr)
            return 2
        if a.pret is None and git_head(root) != g["pin"]():
            print(f"{root} is at {git_head(root)}, not the pin {g['pin']()}", file=sys.stderr)
            return 2
        text = dump(build(root, game))
        if a.check:
            if not out.exists() or out.read_text(encoding="utf-8") != text:
                print(f"{out} is stale -- re-run tools/gen_gen3_wild.py --game {game}", file=sys.stderr)
                status = 1
                continue
            print(f"{out.name} is up to date")
            continue
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    return status


if __name__ == "__main__":
    sys.exit(main())
