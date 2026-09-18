#!/usr/bin/env python3
"""Generate data/games/gen1_<foundation>/gifts.json: the narrative (non-static) grants.

`server/adapters/gen1_rby.py`'s `_GIFT_AREAS`/`_FIXED_GIFTS` frozensets (Oak's starter, the
Eevee, the Magikarp salesman, the Silph Co. Lapras, the two Fighting Dojo Poke Balls, the
Cinnabar fossil revival, the Game Corner prizes) were hand-typed literals with no generator
behind them. `server/adapters/gen1_purergb.py` only covers script/object-event STATIC wild
battles (`static_encounters.json`) -- it has no equivalent table at all, so its
`is_gift_area`/`is_fixed_species_gift` miss every one of pureRGB's own narrative gifts
(docs/purergb/PLAN.md A2: Oak starter, Eevee 25, early Lapras 30, Silph Lapras 40, Saffron
nerd fossils/amber 24, Cinnabar revival 30, Magikarp 5, Hitmonlee/chan 30, Game Corner
prizes).

Every `_GivePokemon`/`GivePokemon`/`AddPartyMon` call site in `scripts/*.asm` (`GivePokemon`
itself is `home/give.asm::` -- `b` = species, `c` = level, both foundations) is a row below,
found by grep and pinned to an exact source line so drift breaks the generator instead of
silently going stale. `species` is the INTERNAL id from `constants/pokemon_constants.asm`
(pret's own hex-commented `const` lines; purergb's `const_def` counter, reusing
tools/gen_gen1_statics.py's / tools/gen_gen1_encounters.py's existing parsers -- no third
parser). `species: null` marks a site where the party's OWN state picks the species (the
starter choice, a fossil revival keyed off which fossil/amber the player handed over): those
sites are read from a register (`ld a,[wCurPartySpecies]` / `[wFossilMon]`), not an
immediate, so no source literal exists to read.

`fixed_species` is a per-SITE fact: true iff this exact call site always hands over the one
species named here, regardless of anything upstream (an Eevee gift, or one specific Fighting
Dojo room, is deterministic; Oak's starter and a fossil revival are not). The AREA-level
`_FIXED_GIFTS` vanilla still hard-codes is a coarser derivation from these same facts: an area
is a "fixed-species gift area" iff its gifts resolve to exactly one DISTINCT known species
(Fighting Dojo's area has two fixed sites but two different species, so the AREA is not
"fixed"; the Game Corner's six fixed prizes are six different species, same story). See
tests/unit/test_gen1_gifts.py::test_pret_gifts_reproduce_the_legacy_frozensets for the
derivation, spelled out once, against the literals it must reproduce exactly.

This tool does NOT change `Gen1Adapter`'s runtime: vanilla keeps reading its own literals
(the test above is the proof the JSON and the literals agree, not a switch to read the JSON
at runtime -- flipping that switch is a separate, non-additive change left to the caller).
`Gen1PureRGBAdapter.is_gift_area`/`is_fixed_species_gift` DO read this file (§ the adapter
has no narrative-gift table at all today), unioned with its existing static-site check.
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
from tools.gen_gen1_statics import species_constants as _pret_species_to_id  # noqa: E402,I001

_MAP_CONST = re.compile(r"^\s*map_const\s+([A-Z][A-Z0-9_]*)\s*,.*?;\s*\$([0-9A-Fa-f]{2,3})\b")


def _map_ids(root: str) -> dict[str, int]:
    """MAP_CONSTANT -> the id wCurMap holds for it, tolerant of a trailing note comment."""
    out = {}
    path = os.path.join(root, "constants", "map_constants.asm")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _MAP_CONST.match(line)
            if m:
                out[m.group(1)] = int(m.group(2), 16)
    return out


class Gift:
    """One `GivePokemon`/`AddPartyMon` call site."""

    def __init__(self, map_const: str, kind: str, species_const: str | None, level: int,
                fixed_species: bool, cite: str, assert_rel: str, assert_needle: str):
        self.map_const = map_const
        self.kind = kind
        self.species_const = species_const
        self.level = level
        self.fixed_species = fixed_species
        self.cite = cite
        self.assert_rel = assert_rel
        self.assert_needle = assert_needle


# kind: "starter" (Oak's lab choice) | "fossil" (a fossil/amber revival) | "prize" (Game
# Corner / Fighting Dojo, paid for or fought for) | "npc_gift" (handed over free, no choice
# beyond taking it).
_PRET_GIFTS = [
    Gift("OAKS_LAB", "starter", None, 5, False,
         "scripts/OaksLab.asm:931", "scripts/OaksLab.asm", "call AddPartyMon"),
    Gift("CELADON_MANSION_ROOF_HOUSE", "npc_gift", "EEVEE", 25, True,
         "scripts/CeladonMansionRoofHouse.asm:15-16",
         "scripts/CeladonMansionRoofHouse.asm", "lb bc, EEVEE, 25"),
    Gift("CINNABAR_LAB_FOSSIL_ROOM", "fossil", None, 30, False,
         "scripts/CinnabarLabFossilRoom.asm:79-80",
         "scripts/CinnabarLabFossilRoom.asm", "ld c, 30"),
    Gift("FIGHTING_DOJO", "prize", "HITMONLEE", 30, True,
         "scripts/FightingDojo.asm:234,245", "scripts/FightingDojo.asm", "ld a, HITMONLEE"),
    Gift("FIGHTING_DOJO", "prize", "HITMONCHAN", 30, True,
         "scripts/FightingDojo.asm:268,279", "scripts/FightingDojo.asm", "ld a, HITMONCHAN"),
    Gift("MT_MOON_POKECENTER", "npc_gift", "MAGIKARP", 5, True,
         "scripts/MtMoonPokecenter.asm:47-48",
         "scripts/MtMoonPokecenter.asm", "lb bc, MAGIKARP, 5"),
    Gift("SILPH_CO_7F", "npc_gift", "LAPRAS", 15, True,
         "scripts/SilphCo7F.asm:310-311", "scripts/SilphCo7F.asm", "lb bc, LAPRAS, 15"),
]

# Game Corner: PrizeMonLevelDictionary (data/events/prize_mon_levels.asm) under IF DEF(_RED),
# read as a source assert (the block itself) plus a regex extraction so a version bump in the
# levels does not silently go undetected -- the literal below is only the label list, not the
# levels, which come from the assert text itself.
_GAME_CORNER_PRET_SPECIES = ["ABRA", "CLEFAIRY", "NIDORINA", "DRATINI", "SCYTHER", "PORYGON"]

_PURERGB_GIFTS = [
    Gift("OAKS_LAB", "starter", None, 5, False,
         "scripts/OaksLab.asm:843", "scripts/OaksLab.asm", "call AddPartyMon"),
    Gift("CELADON_MANSION_ROOF_HOUSE", "npc_gift", "EEVEE", 25, True,
         "scripts/CeladonMansionRoofHouse.asm:20,22",
         "scripts/CeladonMansionRoofHouse.asm", "lb bc, EEVEE, 25"),
    Gift("CELADON_HOTEL", "npc_gift", "LAPRAS", 30, True,
         "scripts/CeladonHotel.asm:77,79", "scripts/CeladonHotel.asm", "lb bc, LAPRAS, 30"),
    Gift("SILPH_CO_7F", "npc_gift", "LAPRAS", 40, True,
         "scripts/SilphCo7F.asm:269,271", "scripts/SilphCo7F.asm", "lb bc, LAPRAS, 40"),
    Gift("CINNABAR_LAB_FOSSIL_ROOM", "fossil", None, 30, False,
         "scripts/CinnabarLabFossilRoom.asm:46-48",
         "scripts/CinnabarLabFossilRoom.asm", "ld c, 30"),
    Gift("FOSSIL_GUYS_HOUSE", "fossil", None, 24, False,
         "scripts/FossilGuysHouse.asm:98-100", "scripts/FossilGuysHouse.asm", "ld c, 24"),
    Gift("FOSSIL_GUYS_HOUSE", "fossil", "AERODACTYL", 24, True,
         "scripts/FossilGuysHouse.asm:134-135",
         "scripts/FossilGuysHouse.asm", "lb bc, AERODACTYL, 24"),
    Gift("MT_MOON_POKECENTER", "npc_gift", "MAGIKARP", 5, True,
         "scripts/MtMoonPokecenter.asm:35-36",
         "scripts/MtMoonPokecenter.asm", "lb bc, MAGIKARP, 5"),
    Gift("FIGHTING_DOJO", "prize", "HITMONLEE", 30, True,
         "scripts/FightingDojo.asm:290,300", "scripts/FightingDojo.asm", "ld a, HITMONLEE"),
    Gift("FIGHTING_DOJO", "prize", "HITMONCHAN", 30, True,
         "scripts/FightingDojo.asm:326,336", "scripts/FightingDojo.asm", "ld a, HITMONCHAN"),
]

# pureRGB's Game Corner overwrites vanilla's prize roster entirely (data/events/prizes.asm:
# "PureRGBnote: CHANGED: different prize pokemon and TMs") with ONE fixed roster (no per-title
# IF DEF split) -- six prizes, six distinct species, each individually deterministic.
_GAME_CORNER_PURERGB = [("JYNX", 20), ("ELECTABUZZ", 20), ("TANGELA", 20),
                        ("DRATINI", 18), ("DITTO", 25), ("PORYGON", 20)]

_RED_BLOCK = re.compile(r"IF DEF\(_RED\)(.*?)ENDC", re.S)
_LEVEL_ROW = re.compile(r"db\s+([A-Z0-9_]+),\s*(\d+)")


def _game_corner_pret_levels(pret_root: str) -> dict[str, int]:
    """{SPECIES: level} for Red, parsed out of PrizeMonLevelDictionary's IF DEF(_RED) block."""
    text = gf.read_source("pret", "data/events/prize_mon_levels.asm")
    block = _RED_BLOCK.search(text)
    if not block:
        raise SystemExit("gifts: prize_mon_levels.asm has no IF DEF(_RED) block")
    levels = dict(_LEVEL_ROW.findall(block.group(1)))
    missing = [s for s in _GAME_CORNER_PRET_SPECIES if s not in levels]
    if missing:
        raise SystemExit(f"gifts: Red prize table is missing {missing}")
    return {s: int(levels[s]) for s in _GAME_CORNER_PRET_SPECIES}


def _row(map_ids: dict[str, int], species_ids: dict[str, int], gift: Gift, natdex) -> dict:
    if gift.map_const not in map_ids:
        raise SystemExit(f"gifts: unknown map const {gift.map_const}")
    species = species_ids[gift.species_const] if gift.species_const else None
    if gift.species_const and gift.species_const not in species_ids:
        raise SystemExit(f"gifts: unknown species const {gift.species_const}")
    return {
        "map_id": map_ids[gift.map_const], "map_const": gift.map_const,
        "species": species, "natdex": natdex(species) if species is not None else None,
        "level": gift.level, "kind": gift.kind, "fixed_species": gift.fixed_species,
        "source": gift.cite,
    }


def _check_asserts(foundation: str, gifts: list[Gift]) -> None:
    for gift in gifts:
        gf.assert_source(foundation, gift.assert_rel, gift.assert_needle)


def build_pret() -> dict:
    from server.adapters import gen1_codec as codec

    root = gf.source_root("pret")
    _check_asserts("pret", _PRET_GIFTS)
    map_ids = _map_ids(str(root))
    species_ids = _pret_species_to_id(str(root))
    levels = _game_corner_pret_levels(str(root))

    rows = [_row(map_ids, species_ids, g, codec.internal_to_natdex) for g in _PRET_GIFTS]
    for species in _GAME_CORNER_PRET_SPECIES:
        g = Gift("GAME_CORNER_PRIZE_ROOM", "prize", species, levels[species], True,
                 "data/events/prize_mon_levels.asm (IF DEF(_RED))",
                 "data/events/prize_mon_levels.asm", f"db {species},")
        rows.append(_row(map_ids, species_ids, g, codec.internal_to_natdex))
    return {"schema": "gen1-gifts-v1", "source": "pret 405b624 (Red prize table)", "gifts": rows}


def build_purergb() -> dict:
    root = gf.source_root("purergb")
    _check_asserts("purergb", _PURERGB_GIFTS)
    map_ids = _map_ids(str(root))
    species_ids = _purergb_species_to_id(str(root / "constants" / "pokemon_constants.asm"))

    species_pack = json.loads((gf.data_dir("purergb") / "species_index.json")
                              .read_text(encoding="utf-8"))["species"]

    def natdex(internal: int) -> int:
        return species_pack[str(internal)]["dex"]

    rows = [_row(map_ids, species_ids, g, natdex) for g in _PURERGB_GIFTS]
    prize_text = gf.read_source("purergb", "data/events/prize_mon_levels.asm")
    levels = dict(_LEVEL_ROW.findall(prize_text))
    for species, level in _GAME_CORNER_PURERGB:
        if levels.get(species) != str(level):
            raise SystemExit(f"gifts: purergb prize table {species} is {levels.get(species)!r}, "
                             f"expected {level}")
        g = Gift("GAME_CORNER_PRIZE_ROOM", "prize", species, level, True,
                 "data/events/prize_mon_levels.asm",
                 "data/events/prize_mon_levels.asm", f"db {species},")
        rows.append(_row(map_ids, species_ids, g, natdex))
    commit = gf.lock("purergb")["source"]["commit"][:12]
    return {"schema": "gen1-gifts-v1", "source": f"purergb {commit}", "gifts": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--foundation", default="pret", choices=["pret", "purergb"])
    ap.add_argument("--check", action="store_true",
                    help="fail if the file on disk differs from what the source says")
    args = ap.parse_args()
    doc = build_pret() if args.foundation == "pret" else build_purergb()
    out_path = gf.data_dir(args.foundation) / "gifts.json"
    rel = os.path.relpath(out_path, REPO)
    if args.check:
        if not out_path.exists() or json.loads(out_path.read_text(encoding="utf-8")) != doc:
            print(f"{rel} is stale -- re-run without --check", file=sys.stderr)
            return 1
        print(f"{rel} matches source ({len(doc['gifts'])} gifts)")
        return 0
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {rel}: {len(doc['gifts'])} gifts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
