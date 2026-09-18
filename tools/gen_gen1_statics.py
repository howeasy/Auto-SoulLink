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

import tools.gen1_foundation as gf  # noqa: E402,I001
from tools.gen_gen1_encounters import parse_pokemon_constants as _purergb_species_to_id  # noqa: E402,I001

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
    ap.add_argument("--foundation", default="pret", choices=["pret", "purergb"])
    ap.add_argument("--check", action="store_true",
                    help="fail if the file on disk differs from what the decomps say")
    args = ap.parse_args()
    if args.foundation == "purergb":
        return main_purergb(check=args.check)
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


# ---------------------------------------------------------------------------------------------
# pureRGB pipeline (docs/purergb/PLAN.md M1, W2's byte-verified list as the oracle). Unlike
# vanilla's two write shapes (`ld a,SPECIES`/`ld [wCurOpponent],a` or `object_event`), pureRGB
# adds a third: `ld a,SPECIES` / `ld [wEngagedTrainerClass],a` / `ld a,LEVEL` /
# `ld [wEngagedTrainerSet],a` (A12: InitBattleEnemyParameters resolves this into wCurOpponent/
# wCurEnemyLevel for a species below OPP_ID_OFFSET). A few statics write LEVEL before SPECIES
# (the reverse of Route12's Snorlax) -- both orders are matched below, never assumed.
# ---------------------------------------------------------------------------------------------

_LD_A = re.compile(r"^\s*ld a,\s*([A-Za-z_0-9]+)\s*$")
_LD_CUR_OPPONENT = re.compile(r"^\s*ld \[wCurOpponent\],\s*a\s*$")
_LD_CUR_ENEMY_LEVEL = re.compile(r"^\s*ld \[wCurEnemyLevel\],\s*a\s*$")
_LD_ENGAGED_CLASS = re.compile(r"^\s*ld \[wEngagedTrainerClass\],\s*a\s*$")
_LD_ENGAGED_SET = re.compile(r"^\s*ld \[wEngagedTrainerSet\],\s*a\s*$")


def _stripped(lines: list[str], i: int) -> str:
    return lines[i].split(";", 1)[0].rstrip() if 0 <= i < len(lines) else ""


def _four_line_hits(lines: list[str], species: dict[str, int],
                    step1: re.Pattern, step3: re.Pattern, level_first: bool) -> list[tuple[int, str, int]]:
    """Scan for a 4-line ``ld a,X / step1 / ld a,Y / step3`` block, either order.

    ``level_first=False``: X is the species (must be a known const), Y is the level literal.
    ``level_first=True``: X is the level literal, Y is the species.
    """
    out = []
    for i in range(len(lines) - 3):
        m0 = _LD_A.match(_stripped(lines, i))
        if not m0 or not step1.match(_stripped(lines, i + 1)):
            continue
        m2 = _LD_A.match(_stripped(lines, i + 2))
        if not m2 or not step3.match(_stripped(lines, i + 3)):
            continue
        sp_tok, lvl_tok = (m2.group(1), m0.group(1)) if level_first else (m0.group(1), m2.group(1))
        if sp_tok not in species or not lvl_tok.isdigit():
            continue
        out.append((i + 1, sp_tok, int(lvl_tok)))
    return out


def direct_hits(path: str, species: dict[str, int]) -> list[tuple[int, str, int]]:
    """``ld a,SPECIES / ld [wCurOpponent],a / ld a,LEVEL / ld [wCurEnemyLevel],a``."""
    return _four_line_hits(_lines(path), species, _LD_CUR_OPPONENT, _LD_CUR_ENEMY_LEVEL, False)


def level_first_hits(path: str, species: dict[str, int]) -> list[tuple[int, str, int]]:
    """``ld a,LEVEL / ld [wCurEnemyLevel],a / ld a,SPECIES / ld [wCurOpponent],a``."""
    return _four_line_hits(_lines(path), species, _LD_CUR_ENEMY_LEVEL, _LD_CUR_OPPONENT, True)


def engaged_hits(path: str, species: dict[str, int]) -> list[tuple[int, str, int]]:
    """``ld a,SPECIES / ld [wEngagedTrainerClass],a / ld a,LEVEL / ld [wEngagedTrainerSet],a``."""
    return _four_line_hits(_lines(path), species, _LD_ENGAGED_CLASS, _LD_ENGAGED_SET, False)


def object_event_hits(path: str, species_filter: set[str] | None = None
                      ) -> list[tuple[int, str, int]]:
    """(line, species_const, level) for every ``object_event`` row with a species field."""
    out = []
    for number, line in enumerate(_lines(path), 1):
        m = _OBJECT.match(line)
        if not m:
            continue
        fields = [f.strip() for f in m.group(1).split(",")]
        if len(fields) < 8:
            continue
        sp = fields[6]
        if species_filter is not None and sp not in species_filter:
            continue
        if not fields[7].lstrip("-").isdigit():
            continue
        out.append((number, sp, int(fields[7])))
    return out


# Each row: (map const, source-relative file, kind, matcher name, species token or None for
# "take the single/next match", event_flag or None when the script has no repeatable gate).
_PURERGB_STATIC_ROWS = [
    ("ROUTE_12", "scripts/Route12.asm", "script", "direct", None,
     "EVENT_BEAT_ROUTE12_SNORLAX"),
    ("ROUTE_16", "scripts/Route16.asm", "script", "direct", None,
     "EVENT_BEAT_ROUTE16_SNORLAX"),
    ("CERULEAN_ROCKET_HOUSE_B1F", "scripts/CeruleanRocketHouseB1F.asm", "script", "level_first",
     None, None),  # a one-time machine trade-style encounter; no CheckEvent gate in the script
    ("POKEMON_TOWER_6F", "scripts/PokemonTower6F.asm", "script", "direct", None,
     "EVENT_BEAT_GHOST_MAROWAK"),
    ("VIRIDIAN_CITY", "scripts/ViridianCity.asm", "script", "level_first", None, None),
    ("CERULEAN_CAVE_B1F", "scripts/CeruleanCaveB1F.asm", "script", "engaged", "MEWTWO",
     "EVENT_BEAT_MEWTWO"),
    ("POWER_PLANT", "data/maps/objects/PowerPlant.asm", "object_event", "object", "ZAPDOS",
     "EVENT_BEAT_ZAPDOS"),
    ("POWER_PLANT_ROOF", "data/maps/objects/PowerPlantRoof.asm", "object_event", "object",
     "ZAPDOS", "EVENT_BEAT_ZAPDOS"),
    ("SEAFOAM_ISLANDS_B4F", "scripts/SeafoamIslandsB4F.asm", "script", "engaged", "ARTICUNO",
     "EVENT_BEAT_ARTICUNO"),
    ("CINNABAR_VOLCANO", "scripts/CinnabarVolcano.asm", "script", "engaged", "MOLTRES",
     "EVENT_BEAT_MOLTRES"),
    ("VICTORY_ROAD_2F", "data/maps/objects/VictoryRoad2F.asm", "object_event", "object",
     "MOLTRES", "EVENT_BEAT_MOLTRES"),
    ("CINNABAR_VOLCANO", "scripts/CinnabarVolcano.asm", "script", "engaged", "MAGMAR",
     "EVENT_DEFEATED_VOLCANO_MAGMAR"),
    ("SEAFOAM_ISLANDS_1F", "scripts/SeafoamIslands1F.asm", "script", "engaged", "CLOYSTER",
     "EVENT_DRAGONAIR_EVENT_BEAT_CLOYSTER"),
]

# The 8 Power Plant "disguised item ball" object rows, in source order, each its own flag
# (A2/W2: item-ball-shaped Voltorb/Electrode encounters, gated individually so re-entering the
# map doesn't re-fight an already-caught one).
_POWER_PLANT_VOLTORB_FLAGS = [f"EVENT_BEAT_POWER_PLANT_VOLTORB_{i}" for i in range(8)]


def build_purergb() -> dict:
    root = gf.source_root("purergb")
    species = _purergb_species_to_id(str(root / "constants" / "pokemon_constants.asm"))
    # One level of `DEF ALIAS EQU NAME` -- RESTLESS_SOUL is how pureRGB spells the ghost
    # Marowak's battle species too (constants/pokemon_constants.asm:209), same as pret.
    for line in _lines(str(root / "constants" / "pokemon_constants.asm")):
        m = _ALIAS.match(line)
        if m and m.group(2) in species:
            species[m.group(1)] = species[m.group(2)]
    map_ids = {}
    for line in (root / "constants" / "map_constants.asm").read_text(encoding="utf-8").splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^map_const\s+([A-Z0-9_]+)\s*,", line)
        if m:
            map_ids[m.group(1)] = len(map_ids)

    event_flags = gf.read_source("purergb", "constants/event_constants.asm")

    def assert_flag(name: str | None) -> None:
        if name and f"const {name}" not in event_flags and f"EXPORT {name}" not in event_flags:
            raise SystemExit(f"purergb statics: {name} not found in event_constants.asm")

    records: list[dict] = []
    for map_const, rel, kind, matcher, token, event_flag in _PURERGB_STATIC_ROWS:
        if map_const not in map_ids:
            raise SystemExit(f"purergb statics: unknown map const {map_const}")
        assert_flag(event_flag)
        path = str(root / rel)
        if not os.path.exists(path):
            raise SystemExit(f"purergb statics: {map_const}: missing {rel}")
        if matcher == "direct":
            hits = direct_hits(path, species)
        elif matcher == "level_first":
            hits = level_first_hits(path, species)
        elif matcher == "engaged":
            hits = engaged_hits(path, species)
        else:
            hits = object_event_hits(path, species_filter={token} if token else None)
        if token:
            hits = [h for h in hits if h[1] == token]
        if not hits:
            raise SystemExit(f"purergb statics: {map_const} ({rel}): no {matcher} match for "
                             f"{token or 'any species'} -- parser or checkout is wrong")
        line, sp_const, level = hits[0]
        records.append({
            "map_id": map_ids[map_const], "map_const": map_const,
            "species": species[sp_const], "species_const": sp_const, "level": level,
            "event_flag": event_flag, "kind": kind, "cite": f"{rel}:{line}",
        })

    # Power Plant's 8 disguised-ball object rows, matched in source order, one flag each.
    pp_path = str(root / "data" / "maps" / "objects" / "PowerPlant.asm")
    pp_hits = object_event_hits(pp_path, species_filter={"VOLTORB", "ELECTRODE"})
    if len(pp_hits) != len(_POWER_PLANT_VOLTORB_FLAGS):
        raise SystemExit(f"purergb statics: Power Plant has {len(pp_hits)} Voltorb/Electrode "
                         f"object rows, expected {len(_POWER_PLANT_VOLTORB_FLAGS)}")
    for (line, sp_const, level), flag in zip(pp_hits, _POWER_PLANT_VOLTORB_FLAGS, strict=True):
        assert_flag(flag)
        records.append({
            "map_id": map_ids["POWER_PLANT"], "map_const": "POWER_PLANT",
            "species": species[sp_const], "species_const": sp_const, "level": level,
            "event_flag": flag, "kind": "object_event",
            "cite": f"data/maps/objects/PowerPlant.asm:{line}",
        })

    # Backward-compatible {map_id: [species,...]} block, same shape as vanilla's file, so the
    # client's `self.statics[tostring(map_id)]` lookup needs no purergb-specific branch.
    statics: dict[str, list[int]] = {}
    cites: dict[str, list[str]] = {}
    for r in sorted(records, key=lambda r: r["map_id"]):
        key = str(r["map_id"])
        statics.setdefault(key, [])
        if r["species"] not in statics[key]:
            statics[key].append(r["species"])
        cites.setdefault(key, []).append(r["cite"])

    return {
        "schema": "gen1-statics-v1", "source": f"purergb {gf.lock('purergb')['source']['commit'][:12]}",
        "statics": {k: sorted(v) for k, v in statics.items()},
        "cites": {k: sorted(v) for k, v in cites.items()},
        "records": sorted(records, key=lambda r: (r["map_id"], r["species"])),
    }


def main_purergb(check: bool) -> int:
    out_path = gf.data_dir("purergb") / "static_encounters.json"
    doc = build_purergb()
    rel = os.path.relpath(out_path, gf.REPO)
    if check:
        if not out_path.exists() or json.loads(out_path.read_text(encoding="utf-8")) != doc:
            print(f"{rel} is stale — re-run without --check", file=sys.stderr)
            return 1
        print(f"{rel} matches source ({len(doc['records'])} records)")
        return 0
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {rel}: {len(doc['records'])} records across {len(doc['statics'])} maps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
