#!/usr/bin/env python3
"""Generate data/games/gen1_rby/static_encounters.json from pret (405b624).

A static (scripted, fixed-species) encounter must NOT consume the map's wild-encounter slot:
the server already recognises a `static_<map>_<dex>` area id (server/adapters/gen1_rby.py),
and the client tags such a battle so both its `capture` and its `no_catch` carry that id. This
tool is where the list of statics comes from -- read out of the decomps, never typed by hand,
so a wrong species or a missing map is a parse failure rather than a silent gap.

TWO RULES, because pret stores the species in two places and neither covers every map:

  * `object_event` with a species constant in the field before the level --
    data/maps/objects/<Map>.asm. The legendary birds, Mewtwo and Power Plant's disguised
    Voltorb/Electrode item-balls are all object-driven, e.g.
    `object_event 4, 9, SPRITE_BIRD, STAY, UP, TEXT_POWERPLANT_ZAPDOS, ZAPDOS, 50`.
    Trainers carry an `OPP_*` class there and item balls carry nothing, so both fall out by
    membership in constants/pokemon_constants.asm rather than by position alone.

  * `ld a, <SPECIES>` IMMEDIATELY followed by `ld [wCurOpponent], a` -- the script that starts
    the battle, e.g. scripts/Route12.asm:33-34 (Snorlax). The adjacency is load-bearing: the
    same `ld a, ARTICUNO` inside a text script two lines above a `call PlayCry`
    (scripts/SeafoamIslandsB4F.asm:162) is a cry, not an encounter.

Internal species indices come from constants/pokemon_constants.asm, whose `const NAME ; $XX`
comments ARE the internal index (SNORLAX $84, dex 143 via data/pokemon/dex_order.asm), with
one level of `DEF ALIAS EQU SPECIES` resolution for RESTLESS_SOUL, which is how pret spells
the Marowak ghost (constants/pokemon_constants.asm:209).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

PRET = os.path.join(REPO, ".cache", "pret", "pokered")
OUT = os.path.join(REPO, "data", "games", "gen1_rby", "static_encounters.json")
SOURCE = "pret 405b624"

# (map constant in constants/map_constants.asm, script, objects). Both files are optional;
# a map that yields nothing is a hard failure.
MAPS = [
    ("ROUTE_12", "scripts/Route12.asm", "data/maps/objects/Route12.asm"),
    ("ROUTE_16", "scripts/Route16.asm", "data/maps/objects/Route16.asm"),
    ("POWER_PLANT", "scripts/PowerPlant.asm", "data/maps/objects/PowerPlant.asm"),
    ("SEAFOAM_ISLANDS_B4F", "scripts/SeafoamIslandsB4F.asm",
     "data/maps/objects/SeafoamIslandsB4F.asm"),
    ("VICTORY_ROAD_2F", "scripts/VictoryRoad2F.asm", "data/maps/objects/VictoryRoad2F.asm"),
    ("CERULEAN_CAVE_B1F", "scripts/CeruleanCaveB1F.asm",
     "data/maps/objects/CeruleanCaveB1F.asm"),
    ("POKEMON_TOWER_6F", "scripts/PokemonTower6F.asm", "data/maps/objects/PokemonTower6F.asm"),
]

_CONST = re.compile(r"^\s*const\s+([A-Z][A-Z0-9_]*)\s*;\s*\$([0-9A-Fa-f]{2})\s*$")
_ALIAS = re.compile(r"^\s*DEF\s+([A-Z][A-Z0-9_]*)\s+EQU\s+([A-Z][A-Z0-9_]*)\s*$")
_MAP_CONST = re.compile(r"^\s*map_const\s+([A-Z][A-Z0-9_]*)\s*,[^;]*;\s*\$([0-9A-Fa-f]{2})\s*$")
_OBJECT = re.compile(r"^\s*object_event\s+(.*?)\s*$")
_LD_SPECIES = re.compile(r"^\s*ld a,\s*([A-Z][A-Z0-9_]*)\s*$")
_LD_CUR_OPPONENT = re.compile(r"^\s*ld \[wCurOpponent\],\s*a\s*$")


def _lines(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def species_constants(pret: str) -> dict[str, int]:
    """NAME -> internal index, including one level of `DEF ALIAS EQU NAME`."""
    text = _lines(os.path.join(pret, "constants", "pokemon_constants.asm"))
    out = {}
    for line in text:
        m = _CONST.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    for line in text:
        m = _ALIAS.match(line)
        if m and m.group(2) in out:
            out[m.group(1)] = out[m.group(2)]
    return out


def map_ids(pret: str) -> dict[str, int]:
    """MAP_CONSTANT -> the id wCurMap holds for it."""
    out = {}
    for line in _lines(os.path.join(pret, "constants", "map_constants.asm")):
        m = _MAP_CONST.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def object_hits(path: str, species: dict[str, int]) -> list[tuple[int, str]]:
    """(line, symbol) for every object event whose field before the level is a species."""
    out = []
    for number, line in enumerate(_lines(path), 1):
        m = _OBJECT.match(line)
        if not m:
            continue
        fields = [f.strip() for f in m.group(1).split(",")]
        if len(fields) >= 8 and fields[6] in species:
            out.append((number, fields[6]))
    return out


def script_hits(path: str, species: dict[str, int]) -> list[tuple[int, str]]:
    """(line, symbol) for every `ld a, <SPECIES>` that stores straight into wCurOpponent."""
    lines = _lines(path)
    out = []
    for i, line in enumerate(lines):
        m = _LD_SPECIES.match(line)
        if not m or m.group(1) not in species:
            continue
        if i + 1 < len(lines) and _LD_CUR_OPPONENT.match(lines[i + 1]):
            out.append((i + 1, m.group(1)))
    return out


def build() -> dict:
    """The whole document: statics keyed by map id, plus the file:line each entry came from."""
    from server.adapters import gen1_codec as codec

    species = species_constants(PRET)
    ids = map_ids(PRET)
    statics: dict[str, list[int]] = {}
    cites: dict[str, list[str]] = {}
    for name, script_rel, object_rel in MAPS:
        if name not in ids:
            raise SystemExit(f"{name}: not in constants/map_constants.asm")
        hits: list[tuple[str, int, str]] = []          # (file, line, symbol)
        for rel, parser in ((script_rel, script_hits), (object_rel, object_hits)):
            path = os.path.join(PRET, rel)
            if os.path.exists(path):
                hits += [(rel, line, sym) for line, sym in parser(path, species)]
        if not hits:
            raise SystemExit(
                f"{name}: no static species found in {script_rel} or {object_rel} — the "
                f"parser or the checkout is wrong, and a silent gap is worse than a failure")
        for _rel, _line, sym in hits:
            internal = species[sym]
            dex = codec.internal_to_natdex(internal)
            if not dex or codec.natdex_to_internal(dex) != internal:
                raise SystemExit(f"{name}: {sym} (${internal:02X}) does not round-trip "
                                 f"through the codec's dex table")
        key = str(ids[name])
        statics[key] = sorted({species[sym] for _rel, _line, sym in hits})
        cites[key] = sorted({f"{rel}:{line}" for rel, line, _sym in hits})
    # Numeric order, because these keys are ids and not words.
    ordered = {key: statics[key] for key in sorted(statics, key=int)}
    return {"schema": "gen1-statics-v1", "source": SOURCE, "statics": ordered,
            "cites": {key: cites[key] for key in ordered}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="fail if the file on disk differs from what the decomps say")
    args = ap.parse_args()
    doc = build()
    rel = os.path.relpath(OUT, REPO)
    if args.check:
        with open(OUT, encoding="utf-8") as f:
            on_disk = json.load(f)
        if on_disk != doc:
            print(f"{rel} is stale — re-run without --check", file=sys.stderr)
            return 1
        print(f"{rel} matches {SOURCE}")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(json.dumps(doc["statics"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
