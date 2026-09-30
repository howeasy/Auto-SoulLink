"""Generate data/games/gen3_exp/28877d73/calc_names.json (XC2).

Diffs the expansion data pack's real names (species/moves/items/abilities)
against the damage calc's gen-9 name sets (tools/gen_rr_priority_trainers.py:
calc_name_sets(9)) and writes only the ROM-spelling -> calc-spelling entries
that differ, the same shape as data/games/gen3_frlge/calc_names.json.
Gen3ExpansionAdapter.calc_name() looks names up here, falling back to
identity (server/adapters/gen3_frlge.py:671-675 pattern).

Only items with a real hold effect are checked: the calc's item table is a
held-item list (no medicine/key items/Poke Balls), so a ROM item with
holdEffect == 0 can never reach calc_name("item", ...) in practice.

--check compares the existing file without writing (same convention as
tools/extract_expansion_data.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
from tools.gen_rr_priority_trainers import calc_name_sets  # noqa: E402

DATA_PACK = _REPO_ROOT / "data/games/gen3_exp/28877d73/data.json"
OUTPUT = _REPO_ROOT / "data/games/gen3_exp/28877d73/calc_names.json"
_SENTINEL_NAME = re.compile(r"^[\s?\-]*$")

# Abilities/species with more than one calc variant (formes) collapse to one
# default, the same accepted simplification as gen3_frlge.py's own
# 'Aegislash' -> 'Aegislash-Shield' entry (a single flat name has no species
# context to disambiguate a forme).
_FORME_DEFAULTS = {
    "species": {"Aegislash": "Aegislash-Shield"},
    "ability": {"As One": "As One (Glastrier)", "Embody Aspect": "Embody Aspect (Teal)"},
}

# Names with no calc-9 equivalent at all (homebrew/expansion-only content, or
# real Gen 9 content this calc fork doesn't implement) -- design doc §3 point 2.
EXPECTED_UNRESOLVED = {
    "species": set(),
    "move": set(),
    "ability": {"Dragonize", "Eelevate", "Fire Mane", "Mega Sol", "Piercing Drill", "Spicy Spray"},
    "item": {
        "Absolite Z", "Amulet Coin", "Barbaracite", "Baxcalibrite", "Chandelurite",
        "Chesnaughtite", "Chimechite", "Cleanse Tag", "Clefablite", "Crabominite",
        "Darkranite", "Delphoxite", "Dragalgite", "Dragoninite", "Drampanite",
        "Eelektrossite", "Emboarite", "Everstone", "Excadrite", "Exp. Share",
        "Falinksite", "Feraligite", "Floettite", "Froslassite", "Garchompite Z",
        "Glimmoranite", "Golisopite", "Golurkite", "Greninjite", "Hawluchanite",
        "Heatranite", "Lucarionite Z", "Luck Incense", "Lucky Egg", "Magearnite",
        "Malamarite", "Meganiumite", "Meowsticite", "Pure Incense", "Pyroarite",
        "Raichunite X", "Raichunite Y", "Scolipite", "Scovillainite", "Scraftinite",
        "Skarmorite", "Smoke Ball", "Soothe Bell", "Staraptite", "Starminite",
        "Tatsugirinite", "Victreebelite", "Zeraorite", "Zygardite",
    },
}


def _real_names(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows if r.get("name") and not _SENTINEL_NAME.fullmatch(r["name"])]


def _resolve(name: str, calc_set: set[str], forme_defaults: dict[str, str]) -> str | None:
    """The calc spelling for `name`, or None if nothing (direct, normalization,
    or a documented forme default) resolves it."""
    if name in calc_set:
        return None  # identity already works; no table entry needed
    if name in forme_defaults:
        return forme_defaults[name]
    nfd = unicodedata.normalize("NFD", name)
    if nfd in calc_set:
        return nfd
    curly = name.replace("'", "’")
    if curly in calc_set:
        return curly
    symbol = name.replace("♀", "-F").replace("♂", "-M")
    if symbol in calc_set:
        return symbol
    lowered_of = re.sub(r"\bOf\b", "of", name)
    if lowered_of in calc_set:
        return lowered_of
    return None  # genuinely unresolved -- must be in EXPECTED_UNRESOLVED


def build() -> tuple[dict, dict[str, set[str]]]:
    data = json.loads(DATA_PACK.read_text(encoding="utf-8"))
    calc_sets = calc_name_sets(9)
    rom_names = {
        "species": _real_names(data["species"]),
        "move": _real_names(data["moves"]),
        "ability": _real_names(data["abilities"]),
        "item": [r["name"] for r in data["items"]
                 if r.get("holdEffect", 0) != 0 and r.get("name")
                 and not _SENTINEL_NAME.fullmatch(r["name"])],
    }
    table: dict[str, dict[str, str]] = {}
    unresolved: dict[str, set[str]] = {}
    for kind, names in rom_names.items():
        table[kind] = {}
        unresolved[kind] = set()
        for name in sorted(set(names)):
            mapped = _resolve(name, calc_sets[kind], _FORME_DEFAULTS.get(kind, {}))
            if mapped is not None:
                table[kind][name] = mapped
            elif name not in calc_sets[kind]:
                unresolved[kind].add(name)
    out = {
        "_note": ("Expansion 28877d73 display name -> damage-calc name (calc/calc/src/data/*.ts), "
                  "per kind. Applied by Gen3ExpansionAdapter.calc_name(). Generated by "
                  "tools/gen_expansion_calc_names.py --check against calc_name_sets(9)."),
        **{k: dict(sorted(v.items())) for k, v in table.items()},
    }
    return out, unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare only, do not write")
    args = ap.parse_args()

    out, unresolved = build()
    for kind, names in unresolved.items():
        expected = EXPECTED_UNRESOLVED.get(kind, set())
        surprising = names - expected
        if surprising:
            print(f"UNEXPECTED unresolved {kind}: {sorted(surprising)}", file=sys.stderr)
            return 1
        missing_expected = expected - names
        if missing_expected:
            print(f"NOTE: previously-unresolved {kind} now resolve: {sorted(missing_expected)}",
                  file=sys.stderr)

    if args.check:
        current = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else None
        if current != out:
            print("FAIL: calc_names.json is stale", file=sys.stderr)
            return 1
        print("PASS: calc_names.json matches regeneration")
        return 0

    OUTPUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
