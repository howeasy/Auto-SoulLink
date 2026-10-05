"""Generate calc/src/calc/data/polished.js -- the Polished Crystal species / move / type-chart
dataset the bundled damage calculator swaps into its GEN 3 slot at runtime.

Polished Crystal runs the calc at **gen 3** (docs/polished/CALC.md §1 proves why: modern stat
formula, per-move physical/special split, natures, and a damage roll that is 85-100%, which is
exactly what calc/calc/src/mechanics/gen3.ts does). Only the DATA is swapped; the mechanics module
is untouched. Three additive setters in the vendored data modules do the swap, mirroring the
pureRGB Gen 1 pattern:

    calc/calc/src/data/species.ts  setGen3Species()
    calc/calc/src/data/moves.ts    setGen3Moves()
    calc/calc/src/data/types.ts    setGen3TypeChart()

Why a plain .js under calc/src/ and not a .ts under calc/calc/src/ like purergb.ts: calc/src/
wins over calc/dist/ in server/calc_files.py's resolver, so the dataset is served without
`cd calc && npm run build` -- and a missing dataset degrades to the preview's own "calculator did
not load" note instead of breaking the build. The rest of the engine still comes from the build.

Inputs (never hand-typed):
  - data/games/polished_crystal/species_index.json  (289 species + 102 form rows)
  - data/games/polished_crystal/forms_index.json    (the 46 variant BaseData record indices)
  - data/games/polished_crystal/moves.json          (255 moves: power, type, split)
  - data/games/polished_crystal/items.json          (held-item inventory)
  - the pinned polishedcrystal checkout (POLISHED_SRC / $SLINK_WORK_ROOT/cache/polished/src):
      constants/type_constants.asm   the type list, in engine order
      data/types/type_matchups.asm   the full type-effectiveness table

Usage:
    python tools/gen_polished_calc.py           # write calc/src/calc/data/polished.js
    python tools/gen_polished_calc.py --check   # exit 1 if the file would change
    python tools/gen_polished_calc.py --src DIR # override the pinned checkout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACK = REPO / "data" / "games" / "polished_crystal"
OUT_PATH = REPO / "calc" / "src" / "calc" / "data" / "polished.js"
DEFAULT_SRC = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache" / "polished" / "src"


# Same [a-z0-9]-only, lowercased id scheme as calc/calc/src/util.ts toID(). Every uniqueness check
# below runs on it, because the calc's own lookups are toID()-keyed: two names that collide here
# are two names the calculator cannot tell apart.
def to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def title_case(name: str) -> str:
    return " ".join(word[:1].upper() + word[1:].lower() for word in name.split("_") if word)


# Two ROM spellings the calc spells differently. Everything else is the pack's own display name.
# Mirrors tools/gen_purergb_calc_patch.py's ORDINARY_NAME_FIXUPS; pinned by
# tests/unit/test_gen_polished_calc.py against this generator's output AND against
# server/adapters/gen2_polished.py's CALC_SPECIES_FIXUPS, so the two cannot drift apart silently.
SPECIES_FIXUPS = {
    "Nidoran♀": "Nidoran-F",
    "Nidoran♂": "Nidoran-M",
}

MULTIPLIER = {
    "SUPER_EFFECTIVE": 2,
    "NOT_VERY_EFFECTIVE": 0.5,
    "NO_EFFECT": 0,
    "EFFECTIVE": 1,
}


def load_pack(name: str) -> dict:
    with (PACK / f"{name}.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def read_source(src: Path, relative: str) -> str:
    path = src / relative
    if not path.is_file():
        raise SystemExit(f"polished source missing: {path}\n"
                         f"set POLISHED_SRC to the pinned checkout "
                         f"(data/polished_sources.lock.json)")
    return path.read_text(encoding="utf-8")


def type_names(src: Path) -> list[str]:
    """constants/type_constants.asm's type list, in engine order, as calc display names.

    UNKNOWN_T is the cartridge's unnamed type; the server adapter renders it '???' everywhere
    (server/adapters/gen2_polished.py _type_display), so the chart must call it the same or the two
    halves of the calc would disagree on one type.
    """
    text = read_source(src, "constants/type_constants.asm")
    block = text.split("const_def", 1)[1].split("DEF NUM_TYPES", 1)[0]
    names = []
    for line in block.splitlines():
        match = re.match(r"\s*const\s+([A-Z_][A-Z0-9_]*)\s*(?:;|$)", line)
        if not match:
            continue
        constant = match.group(1)
        if constant.startswith("NUM_") or constant == "SPECIAL_TYPES":
            continue
        names.append("???" if constant == "UNKNOWN_T" else title_case(constant))
    if names != ["Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost",
                 "Steel", "Fire", "Water", "Grass", "Electric", "Psychic", "Ice", "Dragon",
                 "Dark", "Fairy", "???"]:
        raise SystemExit(f"type_constants.asm no longer yields the expected 19 types: {names}")
    return names


def type_chart(src: Path, names: list[str]) -> dict[str, dict[str, float]]:
    """The full type x type matrix, defaulting to 1x and applying type_matchups.asm's overrides.

    The commented-out `db GROUND, FLYING, NO_EFFECT -- checks airborne state instead` line is
    dropped with the rest of the end-of-line comments, so Ground hits Flying neutrally here. The
    engine decides that row from the target's airborne state instead; docs/polished/CALC.md §4
    lists it as a known approximation.
    """
    const_to_name = {re.sub(r"[^A-Z0-9]+", "", name.upper()): name for name in names}
    const_to_name["UNKNOWN_T"] = "???"
    chart = {attack: dict.fromkeys(names, 1) for attack in names}
    row_re = re.compile(r"db\s+([A-Z0-9_]+),\s*([A-Z0-9_]+),\s*([A-Z_]+)")
    for raw in read_source(src, "data/types/type_matchups.asm").splitlines():
        match = row_re.search(raw.split(";", 1)[0])
        if not match:
            continue
        attack, defence, multiplier = match.groups()
        if attack not in const_to_name or defence not in const_to_name or multiplier not in MULTIPLIER:
            continue
        chart[const_to_name[attack]][const_to_name[defence]] = MULTIPLIER[multiplier]
    return chart


def form_label(row: dict) -> str:
    """'ALOLAN_FORM' on RATTATA -> 'Alolan'; 'TAUROS_PALDEAN_FIRE_FORM' -> 'Paldean Fire'.

    The same derivation server/adapters/gen2_polished.py's _form_label uses for species_name(), so
    the calc-facing key is a pure re-spelling of the display name and never a second naming policy.
    """
    label = row["form_const"].removesuffix("_FORM").removeprefix(row["species_const"] + "_")
    if not label:
        raise SystemExit(f"form {row['form_const']} has no label after stripping its species prefix")
    return label.replace("_", " ").title()


def species_data(index: dict, forms_index: dict, names: list[str]) -> dict[str, dict]:
    """{calc species name: SpeciesData} -- 289 ordinary species + the 46 variant records.

    A variant form is keyed by "<base>-<form label>" because the wire hands the server a variant's
    BaseData RECORD INDEX as its effective species id (forms_index.json, tools/gen_polished_forms.py)
    and calc_species() turns that into exactly this string. Cosmetic forms (Unown letters,
    Magikarp patterns) are deliberately NOT separate rows: they are the same mon in every rule
    (server/adapters/gen2_polished.py __init__), so they resolve to the base species.
    """
    out: dict[str, dict] = {}
    ids: dict[str, str] = {}

    def add(row: dict, key: str) -> None:
        if to_id(key) in ids:
            raise SystemExit(f"species name collision: {key!r} and {ids[to_id(key)]!r} "
                             f"both reduce to {to_id(key)!r}")
        ids[to_id(key)] = key
        # dict.fromkeys: the pack stores a mono-type mon as [T, T]; the engine does NOT dedupe a
        # repeated type (gen3.ts multiplies both slots), which would square every resistance.
        types = list(dict.fromkeys(names[int(number)] for number in row["type_ids"]))
        stats = row["base_stats"]
        out[key] = {
            "types": types,
            # SpeciesData.bs uses the calc's own stat ids. sa/sd are the modern split; the calc's
            # Specie constructor reads bs.sl only for gen < 2, which this table never is.
            "bs": {"hp": stats["hp"], "at": stats["attack"], "df": stats["defense"],
                   "sa": stats["special_attack"], "sd": stats["special_defense"],
                   "sp": stats["speed"]},
            "weightkg": 0,
        }

    for sid in sorted(index["species"], key=int):
        row = index["species"][sid]
        if row.get("classification") != "ordinary":
            continue
        add(row, SPECIES_FIXUPS.get(row["name"], row["name"]))

    records = {row["record_index"]: row for row in forms_index["variant_forms"]
               if row.get("kind") == "variant"}
    for row in index["forms"]:
        if row.get("kind") != "variant" or row["ext"] not in records:
            continue
        base = index["species"][str(row["species"])]
        name = SPECIES_FIXUPS.get(base["name"], base["name"])
        add(row, f"{name}-{form_label(row).replace(' ', '-')}")
    if len(out) != len(index["species"]) + len(records):
        raise SystemExit(f"species table has {len(out)} rows, expected "
                         f"{len(index['species'])} ordinary + {len(records)} variant records")
    return dict(sorted(out.items(), key=lambda pair: to_id(pair[0])))


def moves_data(moves: list[dict], names: list[str]) -> dict[str, dict]:
    """{display name: MoveData} for all 255 Polished moves.

    `category` is mandatory, not cosmetic: calc/calc/src/move.ts:127 derives Physical/Special from
    the move's TYPE when the data has none (that is how gen 1/2 work), and Polished's split is an
    explicit per-move column -- e.g. its Psychic-type Bite is Physical, which the type-derived
    default would get backwards.
    """
    out: dict[str, dict] = {}
    ids: dict[str, str] = {}
    for move in sorted(moves, key=lambda row: row["id"]):
        name = move["name"]
        if to_id(name) in ids:
            raise SystemExit(f"move name collision: {name!r} and {ids[to_id(name)]!r} "
                             f"(id {move['id']}) both reduce to {to_id(name)!r}")
        ids[to_id(name)] = name
        # type_id is the engine's own type column, and type_names() already renders its unnamed
        # entry (UNKNOWN_T, id 18) as "???" -- the same spelling server/adapters/gen2_polished.py's
        # _type_display gives the server, so the two halves cannot disagree about one type.
        out[name] = {"bp": move["power"], "type": names[int(move["type_id"])],
                     "category": move["split"]}
    return dict(sorted(out.items(), key=lambda pair: to_id(pair[0])))


def names_list(values) -> list[str]:
    return sorted(set(values), key=to_id)


def abilities(index: dict) -> list[str]:
    """Every ability the dex grants, title-cased, sorted.

    NOT swapped into the engine. Pokemon/Move match abilities by toID() of the NAME
    (calc/calc/src/pokemon.ts:62, move.ts:114), so the gen 3 ability table already answers every
    ability Polished shares with it -- and overwriting that table would DELETE the effect data the
    gen 3 mechanics read for the ones they do share. Polished-only abilities simply do not fire;
    docs/polished/CALC.md §4 lists that. Gen2PolishedAdapter.supports_abilities() is False anyway,
    so nothing sends an ability name over the wire today.
    """
    out = set()
    for row in index["species"].values():
        out.update(title_case(name) for name in row.get("abilities") or [])
    for row in index["forms"]:
        out.update(title_case(name) for name in row.get("abilities") or [])
    return names_list(out)


def held_items(items: dict) -> list[str]:
    """The items a mon can actually be holding (is_valid_held_item's own rule).

    Not swapped into the engine either, for the same reason as the abilities: the calc's ItemData
    carries per-item multipliers, and the gen 3 mechanics implement only a handful of them
    (Light Ball, Thick Club, Metal Powder, ...). Polished's HELD_TYPE_BOOST / HELD_CATEGORY_BOOST /
    HELD_CHOICE / HELD_LIFE_ORB / HELD_ASSAULT_VEST columns (data/games/polished_crystal/items.json)
    are a gen 5/7 mechanic the gen 3 engine has no code for -- see docs/polished/CALC.md §4.
    """
    out = set()
    for sid, row in items["items"].items():
        if sid == "0" or row.get("placeholder") or row.get("key_item") or row.get("mail"):
            continue
        out.add(row["name"])
    return names_list(out)


def js(value) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(js(item) for item in value) + "]"
    if isinstance(value, dict):
        # Always quote keys: an unquoted `???` is a syntax error, not a style question.
        return "{" + ", ".join(f"{json.dumps(k, ensure_ascii=False)}: {js(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"unhandled value {value!r}")


def rows(table: dict[str, dict]) -> str:
    # ",\n" join, no trailing comma: each table body is strict JSON as well as valid JS.
    return ",\n".join(f"  {json.dumps(name, ensure_ascii=False)}: {js(data)}" for name, data in table.items())


HEADER = """\
// AUTO-GENERATED by tools/gen_polished_calc.py --check. Do not hand-edit.
// Source: data/games/polished_crystal/{species_index,forms_index,moves,items}.json plus the pinned
// polishedcrystal checkout at data/polished_sources.lock.json (v3.2.3, commit 3fa4319...).
// Mechanics, naming policy and the list of approximations: docs/polished/CALC.md.
//
// Swaps the damage calc's GEN 3 species / move / type-chart slot for Polished Crystal's own, and
// back out again. Gen 3 is the mechanics generation Polished matches (CALC.md §1); only data moves.
// Deliberately NOT swapped: abilities and held items (see the comments on each table below).
(function (root) {
  'use strict';
  var exports = root.exports;
  if (!exports || typeof exports.setGen3Species !== 'function') return;

"""

FOOTER = """
  /**
   * Install or remove the Polished Crystal dex in the calc's gen 3 slot. Safe to call at any time
   * and in any order; every other generation's tables are untouched.
   */
  exports.usePolished = function (active) {
    exports.setGen3Species(active ? POLISHED_SPECIES : null);
    exports.setGen3Moves(active ? POLISHED_MOVES : null);
    exports.setGen3TypeChart(active ? POLISHED_TYPE_CHART : null);
    // Crit is x1.5 (x2.25 Sniper) in Polished, x2 everywhere else (CALC.md 4.1). Guarded so an
    // older mechanics build without the hook still loads.
    if (typeof exports.setGen3PolishedCrit === 'function') exports.setGen3PolishedCrit(!!active);
    exports.polishedActive = !!active;
  };
  exports.POLISHED_SPECIES = POLISHED_SPECIES;
  exports.POLISHED_MOVES = POLISHED_MOVES;
  exports.POLISHED_TYPE_CHART = POLISHED_TYPE_CHART;
  exports.POLISHED_ABILITIES = POLISHED_ABILITIES;
  exports.POLISHED_ITEMS = POLISHED_ITEMS;
})(window);
"""


def generate(src: Path) -> str:
    index = load_pack("species_index")
    with (PACK / "forms_index.json").open(encoding="utf-8") as stream:
        forms_index = json.load(stream)
    items = load_pack("items")

    names = type_names(src)
    species = species_data(index, forms_index, names)
    moves = moves_data(load_pack("moves")["moves"], names)
    chart = type_chart(src, names)

    return "".join([
        HEADER,
        "  var POLISHED_SPECIES = {\n", rows(species), "\n};\n\n",
        "  var POLISHED_MOVES = {\n", rows(moves), "\n};\n\n",
        "  var POLISHED_TYPE_CHART = {\n", rows(chart), "\n};\n\n",
        "  // Names only -- see POLISHED_SPECIES's note in this file's generator for why the\n",
        "  // ability and item tables are NOT swapped into the engine.\n",
        "  var POLISHED_ABILITIES = ", js(abilities(index)), ";\n",
        "  var POLISHED_ITEMS = ", js(held_items(items)), ";\n",
        FOOTER,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file would change")
    parser.add_argument("--src", type=Path, default=None, help="pinned polishedcrystal checkout")
    args = parser.parse_args()

    generated = generate(args.src or Path(os.environ.get("POLISHED_SRC") or DEFAULT_SRC))
    if args.check:
        current = None
        if OUT_PATH.is_file():
            with OUT_PATH.open(encoding="utf-8", newline="") as stream:
                current = stream.read()
        if current != generated:
            print(f"{OUT_PATH} is stale; run tools/gen_polished_calc.py", file=sys.stderr)
            return 1
        print("polished.js is up to date")
        return 0

    # newline="" keeps the LF bytes the repo pins (.gitattributes) on Windows too.
    with OUT_PATH.open("w", encoding="utf-8", newline="") as stream:
        stream.write(generated)
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
