"""Generate calc/calc/src/data/purergb.ts: the pureRGB type/species/move patch for the damage
calc's Gen 1 tables, consumed at runtime by ``useDex('purergb')`` (calc/calc/src/data/purergb.ts
itself carries the runtime swap logic too - this tool overwrites the whole file, generated code
and runtime logic together, so the file has exactly one source of truth).

Inputs (never hand-typed, per data/games/gen1_purergb/README.md):
  - data/games/gen1_purergb/types.json    (type_names, species_types)
  - data/games/gen1_purergb/species_index.json (per-species types/stats/classification)
  - data/games/gen1_purergb/moves.json    (per-move type/power/split)
  - the pinned purergb-src checkout (via tools/gen1_foundation.py), for:
      data/types/type_matchups.asm      - full type effectiveness table
      data/pokemon/names.asm            - MonsterNames, in-game display name per internal index
      constants/pokemon_constants.asm   - internal species constant name -> internal index (hex)

See docs/calc_multigen/PURERGB_MECHANICS.md for the naming policy and mechanics this does (and
does not) model.

Usage:
    python tools/gen_purergb_calc_patch.py           # write calc/calc/src/data/purergb.ts
    python tools/gen_purergb_calc_patch.py --check    # exit 1 if the file would change
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen1_foundation as gf  # noqa: E402

DATA_DIR = REPO / "data" / "games" / "gen1_purergb"
OUT_PATH = REPO / "calc" / "calc" / "src" / "data" / "purergb.ts"

# Species classifications worth exposing to the damage calc: ordinary dex mons, alternate forms,
# and spirits (battle-only bosses; not catchable, but a player can still face one). "unused",
# "missingno" and "picture_only" slots are dead ROM space / glitch-only, not worth modelling.
INCLUDED_CLASSIFICATIONS = {"ordinary", "form", "spirit"}

# Same [a-z0-9]-only, lowercased id scheme as calc/calc/src/util.ts toID().
def to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# A handful of ROM MonsterNames spellings the calc renders differently. Everything else is a
# plain Title Case of the all-caps ROM text (see build_ordinary_names below).
ORDINARY_NAME_FIXUPS = {
    "NIDORAN♂": "Nidoran-M",
    "NIDORAN♀": "Nidoran-F",
    "MR.MIME": "Mr. Mime",
    "FARFETCH'D": "Farfetch’d",
}


def title_case_word(word: str) -> str:
    return word[:1].upper() + word[1:].lower() if word else word


def build_ordinary_names(purergb_root: Path) -> list[str]:
    """MonsterNames, 1-indexed by internal species index (index 0 = NO_MON, unused here)."""
    text = (purergb_root / "data" / "pokemon" / "names.asm").read_text(encoding="utf-8")
    names = re.findall(r'dname\s+"([^"]*)"', text)
    out = ["" for _ in range(len(names) + 1)]
    for i, raw in enumerate(names, start=1):
        if raw in ORDINARY_NAME_FIXUPS:
            out[i] = ORDINARY_NAME_FIXUPS[raw]
        else:
            out[i] = " ".join(title_case_word(w) for w in raw.split(" "))
    return out


def build_form_names(purergb_root: Path) -> dict[int, str]:
    """internal index (from the '; $XX' hex comment) -> Title Case of the symbolic constant name,
    for the handful of alternate-form species that reuse their base species' MonsterNames text
    in-game (e.g. internal index 172 displays as "ONIX" just like index 34, so the ROM's own
    display name can't disambiguate them - constants/pokemon_constants.asm's compile-time symbol
    can: HARDENED_ONIX, VOLCANIC_MAGMAR, etc)."""
    text = (purergb_root / "constants" / "pokemon_constants.asm").read_text(encoding="utf-8")
    out: dict[int, str] = {}
    for m in re.finditer(r"const\s+([A-Z0-9_]+)\s*;\s*\$([0-9A-Fa-f]+)", text):
        name, hexval = m.group(1), m.group(2)
        out[int(hexval, 16)] = " ".join(title_case_word(w) for w in name.split("_"))
    return out


def build_type_chart(purergb_root: Path, type_names: dict[str, str]) -> dict[str, dict[str, float]]:
    """Full type x type matrix (default 1, EFFECTIVE) with type_matchups.asm's overrides applied,
    the same "sparse diff over an implicit 1x" convention pret's TypeEffects table (and the calc's
    own hand-written RBY/GSC charts in data/types.ts) both use."""
    text = (purergb_root / "data" / "types" / "type_matchups.asm").read_text(encoding="utf-8")
    # constants/type_constants.asm spells the Psychic type PSYCHIC_TYPE and Bonemerang
    # BONEMERANG_TYPE to dodge asm keyword/label clashes; map those back to the calc's TypeName.
    const_to_name = {"PSYCHIC_TYPE": "Psychic", "BONEMERANG_TYPE": "Bonemerang"}
    for v in type_names.values():
        const_to_name.setdefault(v.upper(), v)
    mult = {"SUPER_EFFECTIVE": 2, "NOT_VERY_EFFECTIVE": 0.5, "NO_EFFECT": 0, "EFFECTIVE": 1}

    all_types = list(type_names.values()) + ["???"]
    chart = {a: dict.fromkeys(all_types, 1) for a in all_types}

    row_re = re.compile(r"db\s+([A-Z0-9_]+),\s*([A-Z0-9_]+),\s*([A-Z_]+)")
    for line in text.splitlines():
        line = line.split(";", 1)[0]  # strip end-of-line comments before matching
        m = row_re.search(line)
        if not m:
            continue
        atk_const, def_const, mult_const = m.groups()
        if atk_const not in const_to_name or def_const not in const_to_name:
            continue  # the "db -1 ; end" sentinel line
        chart[const_to_name[atk_const]][const_to_name[def_const]] = mult[mult_const]
    return chart


def load_json(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def ts_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def build_species_ts(species_index: dict, ordinary_names: list[str], form_names: dict[int, str],
                      type_names: dict[str, str]) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    for idx_str in sorted(species_index["species"], key=int):
        entry = species_index["species"][idx_str]
        classification = entry["classification"]
        if classification not in INCLUDED_CLASSIFICATIONS:
            continue
        idx = int(idx_str)
        if classification == "ordinary":
            name = ordinary_names[idx]
        elif classification == "spirit":
            name = " ".join(title_case_word(w) for w in entry["name"].split(" "))
        else:  # form
            name = form_names.get(idx)
            if not name:
                warnings.append(f"internal index {idx} ({entry['name']}) form has no "
                                 "pokemon_constants.asm match; skipped")
                continue
        sid = to_id(name)
        if sid in seen_ids:
            warnings.append(f"duplicate species id {sid!r} (internal index {idx}); skipped")
            continue
        seen_ids.add(sid)

        t1, t2 = entry["types"]
        types_ts = f"[{ts_str(type_names[str(t1)])}]" if t1 == t2 else \
            f"[{ts_str(type_names[str(t1)])}, {ts_str(type_names[str(t2)])}]"
        stats = entry["stats"]
        # Gen 1 has one Special stat; the calc's Specie.baseStats always wants both spa and spd
        # (see data/species.ts Specie constructor's `gen >= 2 ? sa : sl` branch, which this
        # object bypasses since it's built directly rather than going through that class).
        base_stats = (f"{{hp: {stats['hp']}, atk: {stats['atk']}, def: {stats['def']}, "
                       f"spa: {stats['spc']}, spd: {stats['spc']}, spe: {stats['spd']}}}")
        # weightkg is unused by calculateRBYGSC (mechanics/gen12.ts) - see PURERGB_MECHANICS.md
        lines.append(
            f"  {ts_str(sid)}: {{kind: 'Species', id: {ts_str(sid)}, "
            f"name: {ts_str(name)}, types: {types_ts}, "
            f"baseStats: {base_stats}, weightkg: 0}},"
        )
    return lines, warnings


def build_moves_ts(moves: list[dict]) -> list[str]:
    lines: list[str] = []
    for m in moves:
        mid = to_id(m["name"])
        lines.append(
            f"  {ts_str(mid)}: {{kind: 'Move', id: {ts_str(mid)}, "
            f"name: {ts_str(m['name'])}, basePower: {m['power']}, "
            f"type: {ts_str(m['type'])}, category: {ts_str(m['split'])}, flags: {{}}}},"
        )
    return lines


def build_type_chart_ts(chart: dict[str, dict[str, float]]) -> list[str]:
    lines: list[str] = []
    for atk in chart:
        row = ", ".join(f"{ts_str(d)}: {v}" for d, v in chart[atk].items())
        lines.append(f"  {ts_str(atk)}: {{{row}}},")
    return lines


HEADER = """\
// AUTO-GENERATED by tools/gen_purergb_calc_patch.py --check. Do not hand-edit.
// Source: data/games/gen1_purergb/{types,species_index,moves}.json plus the pureRGB source
// checkout pinned at data/purergb_sources.lock.json (v2.7.6, commit 7e7a4653...).
// Mechanics and naming policy: docs/calc_multigen/PURERGB_MECHANICS.md.
//
// Swaps calc/calc/src/data/{species,moves,types}.ts's Gen 1 slot for pureRGB's own species,
// moves and type chart at runtime. Species/Moves are exported classes (calc/calc/src/data/
// species.ts, moves.ts) whose per-item lookup tables (SPECIES_BY_ID, MOVES_BY_ID) are private and
// built once at module load, so mutating the exported SPECIES/MOVES arrays after that point does
// nothing - this patches Species.prototype.get/[Symbol.iterator] and Moves.prototype's instead,
// falling through to the original implementation for every gen but 1 (or once useDex('vanilla')
// restores it). Types works differently: calc/calc/src/data/types.ts is this branch's own file
// (not shared with the RR/vanilla generators), so it exports setGen1TypeChart() directly instead
// of needing a prototype patch.
import * as I from './interface';
import {Species} from './species';
import {Moves} from './moves';
import {setGen1TypeChart} from './types';

// Built as untyped object literals (types inferred from the literals themselves, e.g. a species's
// `types` tuple infers fine even for a pureRGB-only name like "Magma") and cast once at export,
// rather than annotating {[id: string]: I.Specie} directly here - I.TypeName is a closed union
// that deliberately excludes pureRGB's 6 extra types (see interface.ts), so a direct annotation
// would need an `as unknown as I.TypeName` on every single species/move's type field instead of
// once here.
const SPECIES_DATA = {
"""

MIDDLE_MOVES = """\
};
export const PURERGB_SPECIES = SPECIES_DATA as unknown as {[id: string]: I.Specie};

const MOVES_DATA = {
"""

MIDDLE_TYPES = """\
};
export const PURERGB_MOVES = MOVES_DATA as unknown as {[id: string]: I.Move};

export const PURERGB_TYPE_CHART: {[atk: string]: {[def: string]: I.TypeEffectiveness}} = {
"""

FOOTER = """\
};

let active = false;

// `as any` throughout: Species.prototype.get's inferred return type is species.ts's private
// `Specie` class (not the I.Specie interface), which is stricter than I.Specie in a couple of
// fields (e.g. abilities.0 excludes ''); duck-typed I.Specie/I.Move objects are all callers
// outside species.ts/moves.ts can construct without those files' cooperation.
const speciesProto = Species.prototype as any;
const movesProto = Moves.prototype as any;
const speciesGet = speciesProto.get;
const speciesIter = speciesProto[Symbol.iterator];
const movesGet = movesProto.get;
const movesIter = movesProto[Symbol.iterator];

speciesProto.get = function (this: any, id: I.ID) {
  if (active && this.gen === 1 && id in PURERGB_SPECIES) return PURERGB_SPECIES[id];
  return speciesGet.call(this, id);
};
speciesProto[Symbol.iterator] = function *(this: any) {
  if (active && this.gen === 1) {
    for (const id in PURERGB_SPECIES) yield PURERGB_SPECIES[id];
    return;
  }
  yield* speciesIter.call(this);
};

movesProto.get = function (this: any, id: I.ID) {
  if (active && this.gen === 1 && id in PURERGB_MOVES) return PURERGB_MOVES[id];
  return movesGet.call(this, id);
};
movesProto[Symbol.iterator] = function *(this: any) {
  if (active && this.gen === 1) {
    for (const id in PURERGB_MOVES) yield PURERGB_MOVES[id];
    return;
  }
  yield* movesIter.call(this);
};

/**
 * Swap the damage calc's Gen 1 species/moves/type chart between vanilla RBY and pureRGB. Affects
 * every Generation(1) instance (there's no per-instance opt-out) and every other generation is
 * untouched. Call once before a pureRGB Gen 1 calculation; call useDex('vanilla') to restore.
 */
export function useDex(target: 'vanilla' | 'purergb'): void {
  active = target === 'purergb';
  setGen1TypeChart(active ? PURERGB_TYPE_CHART as any : null);
}
"""


def generate() -> str:
    types_json = load_json("types.json")
    species_index = load_json("species_index.json")
    moves_json = load_json("moves.json")
    type_names = types_json["type_names"]

    purergb_root = gf.source_root("purergb")
    ordinary_names = build_ordinary_names(purergb_root)
    form_names = build_form_names(purergb_root)
    type_chart = build_type_chart(purergb_root, type_names)

    species_lines, warnings = build_species_ts(species_index, ordinary_names, form_names, type_names)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    moves_lines = build_moves_ts(moves_json["moves"])
    type_lines = build_type_chart_ts(type_chart)

    parts = [
        HEADER,
        "\n".join(species_lines), "\n",
        MIDDLE_MOVES,
        "\n".join(moves_lines), "\n",
        MIDDLE_TYPES,
        "\n".join(type_lines), "\n",
        FOOTER,
    ]
    text = "".join(parts)
    return text.replace("\n", "\r\n")  # match the CRLF line endings of the other data/*.ts files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the output would change")
    args = ap.parse_args()

    generated = generate()
    if args.check:
        current = None
        if OUT_PATH.is_file():
            with open(OUT_PATH, encoding="utf-8", newline="") as f:
                current = f.read()
        if current != generated:
            print(f"{OUT_PATH} is stale; run tools/gen_purergb_calc_patch.py", file=sys.stderr)
            return 1
        print("purergb.ts is up to date")
        return 0

    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(generated)
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
